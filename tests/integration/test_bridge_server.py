"""브릿지 HTTP 서버 통합 테스트 (tests/integration/test_bridge_server.py).

검증 대상(src/core/bridge_server.py):
    - POST /handoff : Handoff 파싱 → Orchestrator().receive_handoff() 위임.
    - 잘못된 JSON 수신 시 400 응답.

테스트 방식 (사실, 검증 가능):
    1. ThreadingHTTPServer 를 0번 포트(임의 미사용 포트)로 기동하여 PORT=10899
       상수 점유를 회피한다. 실제 할당 포트는 server_address[1] 로 획득.
    2. POST /handoff 로 실제 Handoff JSON 을 보내면, bridge_server 가 실제
       Orchestrator().receive_handoff() 를 호출한다(런너 기본생성→LLM stub 반환,
       외부 네트워크 무호출). 응답 200 및 본문 "ok" 포함으로 위임 성공을 검증하고,
       스파이(spy)로 receive_handoff 가 실제로 호출되었음을 명시 검증한다.
    3. 잘못된 JSON POST 시 400 응답을 검증한다.
    4. 각 테스트 종료 시 서버를 shutdown 하여 리소스를 정리한다.

컨벤션: snake_case, 한국어 주석. 표준 라이브러리(http.server/threading/
urllib.request)만 사용.
"""

from __future__ import annotations

import http.server
import threading
from unittest import mock
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

# 실제 핸들러 클래스는 HandoffHandler 임(브리핑의 "HttpHandler" 명칭은
# 의역 — 본 모듈은 실제 심볼명을 사용한다). HOST 는 127.0.0.1 고정 상수.
from core.bridge_server import HOST, HandoffHandler
from core.orchestrator import Orchestrator


@pytest.fixture
def bridge_server() -> Iterator[int]:
    """0번 포트로 브릿지 서버를 기동하고, 종료 시 shutdown 한다.

    Returns:
        실제로 할당된(listen 중인) 포트 번호.
    """
    # PORT=10899 상수를 직접 쓰지 않고 0번 포트 바인딩으로 OS 가 임의 포트를
    # 할당하게 하여 포트 점유 충돌을 회피한다.
    server = http.server.ThreadingHTTPServer((HOST, 0), HandoffHandler)
    port: int = server.server_address[1]

    # daemon 스레드로 serve_forever 수행(테스트 종료 시 강제 종료되어도 안전).
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    try:
        yield port
    finally:
        # 테스트 종료 시 서버 정리.
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_handoff_endpoint(bridge_server: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /handoff → 실제 Orchestrator.receive_handoff 호출 → 200/"ok".

    스파이로 receive_handoff 가 실제 호출되었음을 기록하고, 응답 상태 200 및
    본문에 "ok" 가 포함되는지 검증한다.

    mock CDP bridge 를 주입하여 Runner 가 실제 Chrome 을 spawn/connect 하지
    않도록 우회한다(테스트 env 에는 Chrome 이 없음 → Timeout 제거). 실제 동작
    경로(주입 없이 기본 실제 bridge 사용)는 그대로 보존된다.
    """
    # receive_handoff 호출을 기록하되 실제 구현으로 위임(spy 패턴) — 실제 호출 보장.
    captured: list = []
    original = Orchestrator.receive_handoff

    def _spy(self: Orchestrator, handoff):
        captured.append(handoff)
        return original(self, handoff)

    monkeypatch.setattr(Orchestrator, "receive_handoff", _spy)

    # 실제 Chrome 에 붙지 않는 mock bridge — connect() 시 스폰/연결을 시도하지 않음.
    class _FakeCDPBridge:
        page = mock.MagicMock()

        def connect(self) -> None:
            # 테스트 env 에는 Chrome 이 없으므로 CDP 연결 불가능을 시뮬레이션.
            # Runner.run() 의 except 경로로 폴백되어 LLM 결과만 반환된다.
            raise RuntimeError("no real Chrome in test env — CDP unavailable")

        def detect_and_request_hitl(self):
            return None

    # bridge_server 가 사용하는 Orchestrator 를 mock bridge 주입 버전으로 교체.
    monkeypatch.setattr(
        "core.bridge_server.get_orchestrator",
        lambda: Orchestrator(cdp_bridge=_FakeCDPBridge()),
    )

    url = f"http://{HOST}:{bridge_server}/handoff"
    body = b'{"url":"http://x.com","dom_snapshot":"<html></html>"}'
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as resp:
        status = resp.status
        payload = resp.read().decode("utf-8")

    # (1) 실제 Orchestrator.receive_handoff 가 1회 호출되었는지 명시 검증.
    assert len(captured) == 1
    assert captured[0].url == "http://x.com"
    assert captured[0].dom_snapshot == "<html></html>"

    # (2) HTTP 계층 검증: 상태 200, 본문에 "ok" 포함.
    assert status == 200
    assert "ok" in payload


def test_invalid_json(bridge_server: int) -> None:
    """잘못된 JSON POST → 400 응답 검증."""
    url = f"http://{HOST}:{bridge_server}/handoff"
    # 파싱 불가능한 바디 + application/json Content-Type.
    body = b"{ this is not valid json "
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # 4xx/5xx 는 urlopen 이 HTTPError 로 raises 하므로 code 를 추출해 검증.
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=30)

    # JSON 파싱 실패 → 핸들러가 400 을 반환해야 함.
    assert exc_info.value.code == 400
