"""오케스트레이터 (Orchestrator) — Python bridge 상태 보유자 (design doc §9).

역할:
    Background Script(JS)가 ``forwardToAgent()`` 로 전달한 핸드오프/Human-In-
    The-Loop(HITL) 요청을 수신하는 Python 측 진입점(MVP는 인메모리 큐/직접호출).
    MV3 Service Worker(SW)의 수명 제약을 보완하기 위해 세션 상태를 인메모리로
    보유한다 (§9).

위임 흐름 (§2 아키텍처):
    CS(Content Script) → Background → Python core/orchestrator 가 핸드오프 수신
    → agent runner 로 전달.

제약:
    본 모듈은 봇 회피/익스텐션 우회 로직을 일절 포함하지 않는다 (R2 위반 금지).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from agent.runner import Runner
from core.cdp_bridge import CDPBridge
from core.handoff import Handoff, HITLRequest

# 모듈 전용 로거 (console 출력용).
logger = logging.getLogger(__name__)


class RunnerUnavailableError(RuntimeError):
    """Runner 인스턴스가 없습니다(의존성 미설치)."""

    def __init__(self) -> None:
        super().__init__("Runner 인스턴스가 없습니다(의존성 미설치).")


class Orchestrator:
    """핸드오프/HITL 수신 및 runner 위임 진입점 (§9 Python bridge 상태 보유자)."""

    def __init__(
        self,
        hitl_log_path: str = "logs/hitl_requests.log",
        runner: Runner | None = None,
        cdp_bridge: CDPBridge | None = None,
    ) -> None:
        """오케스트레이터를 초기화한다.

        runner 인스턴스를 보유한다. ``agent.runner`` 는 동일 저장소 내
        모듈이므로 모듈 최상단에서 import 하며 순환 import 가능성은 없다.
        다만 초기화(인스턴스 생성) 실패 시에도 안전하게 ``None`` 으로 폴백한다.

        ``runner`` 가 주입되면 재사용(테스트/DI)하고, ``cdp_bridge`` 가 주입되면
        이를 Runner 에 전달한다. 둘 다 없으면 기본값(실제 ``CDPBridge`` 를 쓰는
        Runner)으로 생성하여 실제 브라우징 능력을 보존한다.

        §9: MV3 SW 수명 제약 보완용 상태(수신 큐/HITL 로그)를 인메모리로 보유.
        """
        # runner 인스턴스 보유. 주입된 runner 가 있으면 재사용(테스트/DI),
        # 없으면 cdp_bridge(옵션)를 주입한 Runner 를 생성. 기본값은 실제 CDPBridge.
        try:
            self.runner: Runner | None = (
                runner if runner is not None else Runner(cdp_bridge=cdp_bridge)
            )
        except Exception as exc:  # runner 의존성 부재 등
            logger.warning("Runner 초기화 실패(의존성 부재 가능): %s", exc)
            self.runner = None

        # CDP 브리지 인스턴스 (지연 초기화). 본 모듈은 CDP 를 직접 구동하지 않으며,
        # runner 가 CDP 제어를 담당한다(중복 호출 제거). 속성은 외부 참조용으로 유지.
        self.cdp: CDPBridge | None = None

        # §9 상태 보유: 수신된 핸드오프 인메모리 큐.
        self._handoff_queue: list[Handoff] = []
        # §9 상태 보유: 수신된 HITL 요청 인메모리 로그.
        self._hitl_log: list[dict] = []
        # HITL file 로그 경로.
        self._hitl_log_path: str = hitl_log_path

        # §9 상태 보유: HITL 대기 상태 머신 (url -> "awaiting" | "resolved").
        # 인메모리 MVP — 영속화는 후속 단계에서 처리한다.
        self._hitl_state: dict[str, str] = {}

    def receive_handoff(self, handoff: Handoff) -> str:
        """핸드오프를 수신하여 runner.run() 으로 위임하고 결과 문자열을 반환한다.

        예외 발생 시 로그를 남기고 빈 문자열("")을 반환한다 (안전 보장).
        """
        # 상태 보유자로서 수신 기록 (§9).
        self._handoff_queue.append(handoff)

        # [기존 Runner 위임 로직 — 절대 삭제 금지]
        # runner 인스턴스 부재 시 명시적 예외, 그 외 runner.run() 위임.
        if self.runner is None:
            raise RunnerUnavailableError()
        try:
            runner_result: str = self.runner.run(handoff)
        except Exception:
            logger.exception("핸드오프 위임 실패 (url=%s)", handoff.url)
            return ""

        # orchestrator 는 runner.run() 결과만 반환한다 (CDP 제어는 runner 가 담당 — 중복 제거).
        return runner_result

    def receive_hitl(self, hitl: HITLRequest) -> None:
        """HITL 요청 수신 시 console/file 로그를 남긴다 (인간 개입 대기 표시).

        실제 중단/재개는 후속 구현에서 처리한다.
        """
        record: dict = {
            "url": hitl.url,
            "reason": hitl.reason,
            "timestamp": hitl.timestamp.isoformat(),
            "logged_at": datetime.now(tz=UTC).isoformat(),
            "status": "awaiting_human",
        }
        # 상태 보유자로서 HITL 로그 기록 (§9).
        self._hitl_log.append(record)

        # console 로그: 인간 개입 대기 표시.
        logger.info("[HITL] 인간 개입 대기: url=%s reason=%s", hitl.url, hitl.reason)

        # file 로그 (JSONL) — console 실패와 무관하게 기록 시도.
        try:
            log_dir: str = os.path.dirname(self._hitl_log_path) or "."
            os.makedirs(log_dir, exist_ok=True)
            with open(self._hitl_log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("HITL file 로그 실패: %s", exc)

    def request_hitl(self, handoff_url: str, reason: str) -> HITLRequest:
        """HITL 요청을 생성하고 receive_hitl() 로 전달한 뒤 동일 객체를 반환한다.

        receive_hitl() 을 래핑하므로 중복 로직을 포함하지 않는다 (단일 책임).
        """
        hitl: HITLRequest = HITLRequest(url=handoff_url, reason=reason)
        self.receive_hitl(hitl)
        return hitl

    def pause_for_human(self, url: str) -> HITLRequest:
        """주어진 url 을 인간 개입 대기 상태로 전환하고 HITL 요청을 생성한다.

        ``_hitl_state[url] = "awaiting"`` 로 상태 머신을 변경한 뒤,
        request_hitl(url, "captcha_detected") 를 통해 HITLRequest 를 반환한다.
        """
        self._hitl_state[url] = "awaiting"
        return self.request_hitl(url, "captcha_detected")

    def resume(self, url: str) -> None:
        """주어진 url 의 인간 개입 대기 상태를 해제(resolved)한다."""
        self._hitl_state[url] = "resolved"

    def is_paused(self, url: str) -> bool:
        """주어진 url 이 인간 개입 대기 상태("awaiting")인지 여부를 반환한다."""
        return self._hitl_state.get(url) == "awaiting"


# 참고: Runner 타입은 모듈 최상단에서 import 되므로 타입 힌트에 바로 사용된다
# (PEP 563, from __future__ import annotations).
