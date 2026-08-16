"""에이전트 도구 계층 (Agent tools layer).

이 모듈은 ``src/agent/tools`` 패키지의 진입점으로, 에이전트가 호출할 수 있는
순수 파싱·요약·레지스트리 도구를 제공한다. 핸드오프(R3, 인간→에이전트 위임)
페이로드를 다루기 위한 다음 세 가지 책임을 가진다.

1. DOM 파싱 (R4, DOM 추출·저장)
   - ``parse_dom``: 익스텐션(JS)이 JSON 문자열로 전송하는 DOM 스냅샷을
     Python dict로 안전하게 파싱한다.
2. 핸드오프 요약 (R3)
   - ``summarize_handoff``: ``Handoff`` 모델을 LLM 프롬프트용 요약 텍스트로
     변환한다(URL + 의도 + 제약 + DOM 요약).
3. 도구 레지스트리
   - ``ToolRegistry``: 에이전트가 호출 가능한 도구를 등록/호출하는 가벼운
     디스패처이다.

설계 경계(작업 원칙):
- 이 계층은 순수 파싱·요약·레지스트리만 담당한다. 봇 탐지 회피/캡차 우회 등의
  책임은 브라우저(헤드풀 + 인간 유사 동작) 계층에 있으며, 익스텐션/agent 계층은
  공유 세션·핸드오프·협업 UI 목적으로만 사용한다.
- ``Handoff`` 모델은 ``core.handoff`` 에서 import 하여 사용한다(데이터 contract
  단일화). 파싱 책임은 본 도구 계층에 두되, 모델 정의는 core에 둔다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from core.handoff import Handoff

# ---------------------------------------------------------------------------
# 1. DOM 파싱 (R4)
# ---------------------------------------------------------------------------


def parse_dom(snapshot: str) -> dict[str, Any]:
    """DOM 스냅샷(JSON 문자열)을 파싱하여 dict로 반환한다.

    익스텐션 Content Script가 ``chrome.runtime``/IPC 로 전송하는 DOM 스냅샷은
    JSON 직렬화된 문자열(str) 형태로 수신된다(handoff.py 문서 참조). 이를
    Python dict로 복원한다.

    매개변수:
        snapshot: JSON 직렬화된 DOM 스냅샷 문자열.

    반환값:
        파싱 성공 시 DOM을 표현하는 dict.
        문자열이 비어 있거나 JSON이 아니면 빈 dict(``{}``)를 반환한다(안전 기본값).

    참고:
        파싱 실패 시 예외를 전파하지 않는다. 도구 호출은 견고해야 하며,
        호출자는 빈 dict 여부로 실패를 판단할 수 있다.
    """
    if not snapshot:
        return {}
    try:
        parsed: Any = json.loads(snapshot)
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}

    # JSON 루트가 객체가 아닐 수도 있으므로(dict 보장이 아님) 정규화한다.
    if isinstance(parsed, dict):
        return parsed
    # 배열/스칼라 등 비객체 루트는 ``root`` 키로 감싸 보관한다.
    return {"root": parsed}


# ---------------------------------------------------------------------------
# 2. 핸드오프 요약 (R3)
# ---------------------------------------------------------------------------


def summarize_handoff(handoff: Handoff) -> str:
    """``Handoff`` 페이로드를 LLM 프롬프트용 요약 텍스트로 변환한다.

    인간→에이전트 위임(R3) 시 전달되는 URL·DOM 스냅샷·의도·제약을 LLM이
    즉시 이해할 수 있는 단일 텍스트 블록으로 정리한다.

    매개변수:
        handoff: ``core.handoff.Handoff`` 위임 페이로드.

    반환값:
        다음 섹션을 포함한 요약 문자열.

        - URL: 위임 대상 페이지 주소
        - 의도(intent): 작업 의도(미지정 시 표기)
        - 제약(constraints): 위임 제약(미지정 시 표기)
        - DOM 요약: 파싱 결과 존재 여부, 문자 길이, 최상위 키(최대 10개)
    """
    # DOM 스냅샷을 파싱하여 요약 정보를 추출한다.
    dom = parse_dom(handoff.dom_snapshot)
    dom_present = bool(dom)
    dom_len = len(handoff.dom_snapshot)
    top_keys = list(dom.keys())[:10] if dom_present else []

    # 의도/제약 미지정 표기.
    intent = handoff.intent if handoff.intent else "(미지정)"
    constraints = handoff.constraints if handoff.constraints else "(없음)"

    lines: list[str] = [
        "[위임 핸드오프 요약]",
        f"URL: {handoff.url}",
        f"의도(intent): {intent}",
        f"제약(constraints): {constraints}",
        "[DOM 스냅샷]",
        f"- 파싱됨: {'예' if dom_present else '아니오'}",
        f"- 원본 길이: {dom_len} 자",
    ]
    if dom_present:
        keys_preview = ", ".join(top_keys) if top_keys else "(키 없음)"
        lines.append(f"- 최상위 키(최대 10): {keys_preview}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. 도구 레지스트리
# ---------------------------------------------------------------------------


class ToolRegistry:
    """에이전트가 호출 가능한 도구를 등록/조회/실행하는 경량 디스패처.

    도구는 이름(str)을 키로 하고 호출 가능 객체(Callable)를 값으로 등록한다.
    등록된 도구는 이름으로 조회하거나 키워드 인자와 함께 실행할 수 있다.
    """

    def __init__(self) -> None:
        """빈 레지스트리로 초기화한다."""
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        """도구를 이름에 매핑하여 등록한다.

        매개변수:
            name: 도구를 식별하는 고유 이름.
            fn: 호출 가능한 도구 구현(Callable).

        예외:
            TypeError: ``fn`` 이 호출 가능하지 않으면 발생.
            ValueError: ``name`` 이 비어 있으면 발생.
        """
        if not name:
            raise ValueError("도구 이름(name)은 비어 있을 수 없습니다.")  # noqa: TRY003
        if not callable(fn):
            raise TypeError(f"등록할 대상은 호출 가능해야 합니다: name={name!r}")  # noqa: TRY003
        self._tools[name] = fn

    def call(self, name: str, **kwargs: Any) -> Any:
        """등록된 도구를 이름으로 호출한다.

        매개변수:
            name: 실행할 도구 이름.
            **kwargs: 도구 호출에 전달할 키워드 인자.

        반환값:
            도구 호출 결과.

        예외:
            KeyError: 이름에 해당하는 도구가 등록되어 있지 않으면 발생.
        """
        if name not in self._tools:
            raise KeyError(f"등록되지 않은 도구입니다: {name!r}")  # noqa: TRY003
        return self._tools[name](**kwargs)

    def get(self, name: str) -> Callable[..., Any]:
        """등록된 도구 callable 을 이름으로 반환한다(실행하지 않음).

        매개변수:
            name: 조회할 도구 이름.

        반환값:
            등록된 호출 가능 객체.

        예외:
            KeyError: 이름에 해당하는 도구가 없으면 발생.
        """
        if name not in self._tools:
            raise KeyError(f"등록되지 않은 도구입니다: {name!r}")  # noqa: TRY003
        return self._tools[name]

    def names(self) -> list[str]:
        """현재 등록된 모든 도구 이름을 반환한다."""
        return list(self._tools.keys())


__all__ = ["Handoff", "ToolRegistry", "parse_dom", "summarize_handoff"]
