"""agent.tools 도구 계층 검증 테스트.

src/agent/tools/__init__.py 에 정의된 순수 파싱·요약·레지스트리 도구를
검증한다. 요구사항은 사실 기반이며, 긍정 케이스는 반환값 비교로,
부정/예외 케이스는 pytest.raises 로 검증한다.

검증 대상:
- parse_dom(snapshot): JSON 문자열을 dict로 안전 파싱 (실패 시 {}).
- summarize_handoff(h): Handoff 를 URL+intent+constraints+DOM 요약 문자열로 변환.
- ToolRegistry: 도구 등록(register) / 호출(call) 및 미등록 호출 예외.
"""

import pytest

from agent.tools import ToolRegistry, parse_dom, summarize_handoff
from core.handoff import Handoff


def test_parse_dom_valid() -> None:
    """유효한 JSON 스냅샷을 그대로 dict 로 파싱한다.

    '{"title":"t","list":[1,2]}' 는 구조 손실 없이 동일 dict 로 복원되어야 한다.
    """
    result = parse_dom('{"title":"t","list":[1,2]}')

    # JSON 객체 루트는 dict 로 직접 반환되는 src 계약.
    assert result == {"title": "t", "list": [1, 2]}


def test_parse_dom_invalid() -> None:
    """파싱 불가 문자열은 안전 기본값 빈 dict({}) 로 폴백한다.

    "not json" 은 유효한 JSON 이 아니므로 예외를 전파하지 않고 {} 를 반환해야 한다.
    """
    result = parse_dom("not json")

    # 도구 호출은 견고해야 하며, 호출자는 빈 dict 여부로 실패를 판단한다.
    assert result == {}


def test_summarize() -> None:
    """Handoff 요약 문자열이 URL·의도·제약을 모두 포함하는지 검증한다.

    url="https://x.com", intent="요약", constraints="광고제외" 인 핸드오프에서
    요약 결과에 세 값이 모두 노출되어야 한다.
    """
    handoff = Handoff(
        url="https://x.com",
        dom_snapshot="<html></html>",
        intent="요약",
        constraints="광고제외",
    )

    summary = summarize_handoff(handoff)

    # 위임 핸드오프 요약은 URL·의도·제약 섹션을 포함한다 (src 계약).
    assert "https://x.com" in summary
    assert "요약" in summary
    assert "광고제외" in summary


def test_registry() -> None:
    """ToolRegistry 등록/호출 및 미등록 호출 예외를 검증한다.

    1) register("echo", lambda x: x) 후 call("echo", x=1) == 1.
    2) 등록되지 않은 이름 호출 시 예외(KeyError) 가 발생해야 한다.
    """
    registry = ToolRegistry()
    registry.register("echo", lambda x: x)

    # 등록된 도구는 전달된 키워드 인자로 실행되어야 한다.
    assert registry.call("echo", x=1) == 1

    # 미등록 도구 호출은 예외를 발생시켜야 한다 (dispatcher 안전성).
    with pytest.raises(KeyError):
        registry.call("missing")
