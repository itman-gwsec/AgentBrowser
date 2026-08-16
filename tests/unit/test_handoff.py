"""Handoff / HITLRequest pydantic 모델 검증 테스트.

src/core/handoff.py 에 정의된 데이터 contract(Handoff, HITLRequest)가
pydantic v2 규칙대로 동작하는지 검증한다. 요구사항은 사실 기반이며
pytest.raises 로 부정 케이스를, 인스턴스 속성 비교로 긍정 케이스를 검증한다.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from core.handoff import Handoff, HITLRequest


def test_required_field() -> None:
    """Handoff 생성 시 dom_snapshot 누락이 ValidationError 를 발생시킨다.

    url 만 전달하고 dom_snapshot 을 생략하면 필수 필드 부재로
    pydantic.ValidationError 가 발생해야 한다 (R3 위임 contract 위반 방지).
    """
    with pytest.raises(ValidationError):
        Handoff(url="x")


def test_defaults() -> None:
    """Handoff 선택 필드 기본값과 timestamp 타입을 검증한다.

    url 와 dom_snapshot 만 전달하면 intent=="" , constraints=="" ,
    version=="1.0" 이며 timestamp 는 datetime 객체여야 한다.
    """
    handoff = Handoff(url="x", dom_snapshot="<html></html>")

    # 기본값이 확정 원칙(버전 기록, 미지정 시 빈 문자열)에 부합하는지 확인.
    assert handoff.version == "1.0"
    assert handoff.intent == ""
    assert handoff.constraints == ""
    # timestamp 는 파싱된 datetime 객체로 보관되어야 함 (src 계약).
    assert isinstance(handoff.timestamp, datetime)


def test_hitl() -> None:
    """HITLRequest 생성 시 reason 일치와 timestamp 타입을 검증한다.

    캡차 위임(R6) 흐름에서 reason 이 그대로 보관되고, timestamp 가
    datetime 객체로 기록되는지 확인한다.
    """
    request = HITLRequest(url="u", reason="captcha_detected")

    assert request.reason == "captcha_detected"
    assert isinstance(request.timestamp, datetime)
