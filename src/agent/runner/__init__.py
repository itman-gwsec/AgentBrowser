"""에이전트 러너 (Agent runner).

Handoff 수신 → LLM 호출 → 액션 계획 반환을 담당하는 오케스트레이션 레이어이다.
design doc §2(Python core/agent 가 핸드오프 수신 → LLM → 액션)와 §4(인간유사동작
타이밍 지터·궤적은 이 레이어에서 담당)의 책임에 부합한다.

주의(§4, 회피 금지):
- 익스텐션(크롬 익스텐션)을 회피/봇우회 목적으로 사용하는 로직은 일절 금지한다.
  §4에 따르면 익스텐션은 회피용으로 부적합하다.
- 인간유사 타이밍 지터(time.sleep 기반)만 이 Python agent 레이어에서 허용된다.
  실제 브라우저 제어(궤적·지터 적용)는 후속 작업에서 도입되며, 본 MVP는
  LLM 응답(액션 계획 텍스트)을 반환하는 스텁으로 구현한다.
"""

from __future__ import annotations

import logging
import random
import time
from typing import TYPE_CHECKING

# src 패키지 루트가 sys.path 에 있으면 절대 임포트가 성립한다(검증 스크립트 참조).
from core.handoff import Handoff, HITLRequest
from core.llm import LLMClient

if TYPE_CHECKING:
    # 런타임 의존성(playwright) 없이 타입만 참조 (순환 import 방지).
    from core.cdp_bridge import CDPBridge

# 모듈 전용 로거 (console 출력용).
logger = logging.getLogger(__name__)

# 인간유사 타이밍 지터의 기본 범위(초). 실제 액션 적용 시 조정 가능.
# 지터는 §4의 "인간유사동작" 원칙에 따라 이 레이어에서 담당한다.
_DEFAULT_JITTER_MIN_S: float = 0.2
_DEFAULT_JITTER_MAX_S: float = 1.2


class Runner:
    """Handoff 를 받아 LLM 으로 액션 계획을 생성하는 러너.

    Attributes:
        llm: LLM 호출에 사용할 클라이언트. 미전달 시 ``core.llm.LLMClient()`` 로 생성.
    """

    def __init__(
        self,
        llm: LLMClient | None = None,
        cdp_bridge: CDPBridge | None = None,
    ) -> None:
        # 미전달 시 기본 LLMClient 인스턴스를 생성한다(env 기반 stub).
        self.llm: LLMClient = llm if llm is not None else LLMClient()
        # CDP 브리지는 주입 가능(DI). 미전달 시 run() 에서 실제 ``CDPBridge()`` 를
        # 지연 생성한다(기본 동작: 실제 Chrome attach). 테스트는 mock bridge 를
        # 주입해 실제 브라우저 spawn/connect 를 우회한다.
        self.cdp_bridge: CDPBridge | None = cdp_bridge

    def run(self, handoff: Handoff) -> str:
        """Handoff 페이로드를 받아 LLM 응답(액션 계획 텍스트)을 반환한다.

        호출 순서:
        1. Handoff 로부터 위임 컨텍스트(URL·DOM 스냅샷·의도·제약)를 프롬프트로 조립.
        2. 인간유사 타이밍 지터 스텁을 적용(§4 — 실제 액션 적용 시 궤적과 함께 확장).
        3. LLM ``complete`` 를 호출하여 액션 계획 텍스트를 받는다.

        실제 브라우저 제어(클릭·타이핑·궤적)는 후속 작업에서 도입된다(MVP stub).
        익스텐션 회피/봇우회 로직은 §4 에 따라 이 레이어에 존재하지 않는다.

        Args:
            handoff: 인간→에이전트 위임 핸드오프 페이로드(R3).

        Returns:
            LLM 이 생성한 액션 계획 텍스트.
        """
        # 1) Handoff → 프롬프트 조립. 파싱은 agent/tools 계층의 책임이므로
        #    여기서는 원시 문자열 컨텍스트를 그대로 프롬프트에 포함한다.
        prompt: str = self._build_prompt(handoff)

        # 2) 인간유사 타이밍 지터 스텁(§4).
        #    실제 액션 적용 시: 이 지터를 마우스 궤적·대기와 함께 확장한다.
        #    익스텐션 회피/봇우회는 금지이므로, 지터는 Python agent 레이어의
        #    순수 동작 지연으로만 사용한다.
        jitter: float = random.uniform(_DEFAULT_JITTER_MIN_S, _DEFAULT_JITTER_MAX_S)
        time.sleep(jitter)

        # 3) LLM 호출 → 액션 계획 텍스트 반환(MVP stub: 실제 브라우저 제어 없음).
        result: str = self.llm.complete(prompt)

        # [CDP 결선 — runner 가 직접 담당] (orchestrator 의 중복 호출 제거로 일관성 확보)
        # runner 위임 결과(result)를 보존한 채 인간유사 검색(SearchDispatcher)을 부가 수행.
        # CDP 브리지/연결/검색 중 무엇이든 실패하면 result 만 반환(안전 fallback).
        #
        # 설계: 기존 ``CDPBridge.control()`` 메서드는 **호환성 유지**(타 코드에서 직접 호출 가능)
        # 하되, 본 run() 에서는 인간유사 검색 경로(SearchDispatcher + Humanizer)를 우선한다.
        try:
            # 지연 import: core↔agent 순환 import 방지 및 CDP 의존성(playwright) 격리.
            from core.cdp_bridge import CDPBridge  # noqa: PLC0415
            from core.humanizer import Humanizer  # noqa: PLC0415
            from core.search import SearchConfig, SearchDispatcher  # noqa: PLC0415

            # 주입된 bridge 가 있으면 재사용(테스트/DI), 없으면 실제 CDPBridge 생성.
            self.cdp = self.cdp_bridge if self.cdp_bridge is not None else CDPBridge()
            self.cdp.connect()
            # 인간유사 검색 경로 우선 (humanizer + SearchDispatcher 연동).
            humanizer = Humanizer()
            dispatcher = SearchDispatcher(SearchConfig(), humanizer, cdp_bridge=self.cdp)
            # MVP 스텁: Handoff 에 query 필드가 없으므로 intent 를 query 로 사용.
            # intent 가 비어 있으면 url 로 fallback 한다.
            query = handoff.intent or handoff.url
            search_out = dispatcher.run(self.cdp.page, query)
            if isinstance(search_out, HITLRequest):
                # 캡차 등 인간 개입 필요 → 안전 fallback 문자열로 치환하여 result 에 병합.
                cdp_result = f"[HITL] 인간 개입 필요 ({search_out.reason}) @ {search_out.url}"
            else:
                cdp_result = search_out
        except Exception as exc:
            logger.warning("[runner] CDP/검색 생략(안전 fallback): %s", exc)
        else:
            result = f"{result}\n[CDP] {cdp_result}"

        return result

    @staticmethod
    def _build_prompt(handoff: Handoff) -> str:
        """Handoff 를 LLM 프롬프트 문자열로 조립한다.

        Args:
            handoff: 위임 핸드오프 페이로드.

        Returns:
            프롬프트 문자열.
        """
        lines: list[str] = [
            "다음은 인간이 위임한 브라우징 작업 컨텍스트이다.",
            f"URL: {handoff.url}",
            f"작업 의도: {handoff.intent or '(미지정)'}",
            f"제약: {handoff.constraints or '(없음)'}",
            f"DOM 스냅샷: {handoff.dom_snapshot}",
            "위 컨텍스트를 바탕에 둔 단계별 액션 계획을 작성하라.",
        ]
        return "\n".join(lines)
