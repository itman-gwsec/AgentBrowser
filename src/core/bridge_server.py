"""익스텐션→Python 핸드오프 수신 HTTP 브릿지 서버 (AgentBrowser R3/R6).

크롬 익스텐션(Background Script)이 ``forwardToAgent()`` 로 전달한 핸드오프/
HITL(Human-In-The-Loop) 요청을 HTTP POST 로 수신하고, Python 계층의
Orchestrator 로 위임한다.

설계 제약:
    - 표준 라이브러리만 사용 (외부 의존성 최소화).
    - bind host 는 127.0.0.1 로 고정하여 외부 노출을 차단한다 (보안).
    - Orchestrator 는 지연 import(lazy import)로 core↔agent 순환 import 를 방지한다.
    - 본 모듈은 봇 회피/익스텐션 우회 로직을 일절 포함하지 않는다 (R2 위반 금지).
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# 핸드오프/HITL 스키마 (pydantic v2 모델). 수신 단계 파싱에 사용된다.
from core.handoff import Handoff, HITLRequest

# Orchestrator 는 순환 import 가 없으므로 모듈 최상단에서 import.
from core.orchestrator import Orchestrator

# 모듈 전용 로거 (console 출력용).
logger = logging.getLogger(__name__)

# 통신 포트 — 기본 10899, 환경변수 BRIDGE_PORT 로 오버라이드 가능.
PORT: int = int(os.environ.get("BRIDGE_PORT", "10899"))

# bind host — 외부 노출 차단을 위해 루프백(loopback)으로 고정.
HOST: str = "127.0.0.1"


def get_orchestrator() -> Orchestrator:
    """Orchestrator 인스턴스를 반환한다 (DI/테스트 오버라이드 가능).

    기본값은 실제 ``Orchestrator()`` 이며, 이는 실제 ``CDPBridge`` 를 사용하는
    Runner 를 생성하여 **실제 브라우징 능력을 보존**한다 (프로덕션 동작 변경 없음).

    테스트는 ``monkeypatch`` 로 이 함수를 교체하여 mock CDP bridge 를 주입함으로써
    실제 Chrome spawn/connect 없이 엔드포인트 위임 경로만 검증할 수 있다.
    """
    return Orchestrator()


class HandoffHandler(BaseHTTPRequestHandler):
    """익스텐션 핸드오프/HITL 요청을 수신하는 HTTP 요청 핸들러.

    ``ThreadingHTTPServer`` 와 결합되어 동시 요청을 스레드 단위로 처리한다.
    """

    # 기본 access log 를 억제하여 stdout 노이즈를 방지한다.
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        """요청 바디를 application/json 으로 파싱하여 dict 로 반환한다.

        Raises:
            ValueError: Content-Type 이 JSON 이 아니거나, 바디가 비었거나,
                JSON 디코딩에 실패한 경우.
        """
        content_type: str = self.headers.get("Content-Type", "")
        if "application/json" not in content_type.lower():
            raise ValueError("Content-Type 이 application/json 이 아닙니다.")  # noqa: TRY003

        length: int = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            raise ValueError("요청 바디(Content-Length)가 비어 있습니다.")  # noqa: TRY003

        raw: bytes = self.rfile.read(length)
        try:
            payload: dict[str, Any] = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"JSON 파싱 실패: {exc}") from exc  # noqa: TRY003

        if not isinstance(payload, dict):
            raise TypeError("JSON 루트가 객체(object)가 아닙니다.")  # noqa: TRY003
        return payload

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        """JSON 응답을 작성한다 (상태 코드와 본문을 인자로 받는다)."""
        data: bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_resume(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """RESUME 요청({url})을 처리한다.

        익스텐션 배너의 [재개] 클릭으로부터 전달된 url 을 수신하여
        ``Orchestrator().resume(url)`` 로 HITL 대기 상태를 해제(resolved)한다.

        Returns:
            (HTTP 상태 코드, 응답 본문) 튜플.
        """
        url = body.get("url")
        if not url:
            return 400, {"error": "url required"}
        get_orchestrator().resume(url)
        return 200, {"ok": True, "url": url}

    def do_POST(self) -> None:
        """POST 요청을 path 별로 분기 처리한다.

        엔드포인트:
            - POST /handoff : Handoff 파싱 → Orchestrator.receive_handoff()
            - POST /hitl    : HITLRequest 파싱 → Orchestrator.receive_hitl()
            - POST /resume  : {url} 수신 → Orchestrator.resume(url)
        파싱/위임 오류 시 400 을 반환한다.
        """
        try:
            payload: dict[str, Any] = self._read_json_body()

            if self.path == "/handoff":
                # pydantic 모델로 검증/파싱.
                handoff: Handoff = Handoff.model_validate(payload)
                get_orchestrator().receive_handoff(handoff)
                self._send_json(200, {"status": "ok"})

            elif self.path == "/hitl":
                hitl: HITLRequest = HITLRequest.model_validate(payload)
                get_orchestrator().receive_hitl(hitl)
                self._send_json(200, {"status": "ok"})

            elif self.path == "/resume":
                status, body = self._handle_resume(payload)
                self._send_json(status, body)

            else:
                self._send_json(404, {"status": "error", "message": "알 수 없는 경로입니다."})

        except ValueError as exc:
            # Content-Type/JSON 파싱/스키마 검증 오류.
            self._send_json(400, {"status": "error", "message": str(exc)})
        except Exception as exc:  # 모델 검증 외 위임 실패 등 예외 포착.
            self._send_json(400, {"status": "error", "message": str(exc)})


def run_server(host: str = HOST, port: int = PORT) -> None:
    """브릿지 HTTP 서버를 기동한다 (호출자: ``__main__`` 블록).

    Args:
        host: bind 할 호스트 (기본 127.0.0.1, 루프백 고정).
        port: listen 할 포트 (기본 10899).
    """
    server: ThreadingHTTPServer = ThreadingHTTPServer((host, port), HandoffHandler)
    logger.info("[bridge_server] 시작: http://%s:%s (Ctrl+C 로 종료)", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("[bridge_server] 종료 요청 수신 — 서버를 닫습니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    # python -m core.bridge_server 로 서버 기동.
    run_server()
