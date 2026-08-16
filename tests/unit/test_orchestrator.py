"""오케스트레이터 단위 테스트 (tests/unit/test_orchestrator.py).

실제 동작 기반 검증(TDD):
- 초기화 시 cdp 는 None, hitl_log_path 는 문자열.
- runner 가 None 인 경우 receive_handoff() 는 RunnerUnavailableError 를 발생
  (빈 문자열 반환이 아님 — 실제 코드 L78 기준).
- receive_hitl() 호출 시 인메모리 로그(status="awaiting_human") 및
  file JSONL 로그에 "awaiting_human"·"captcha" 가 기록됨.

금지: 실제 CDP/LLM 호출. 본 테스트는 인스턴스 생성/속성 덮어쓰기/로컬 파일
기록만 사용하므로 외부 의존성을 건드리지 않는다.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from core.handoff import Handoff, HITLRequest
from core.orchestrator import Orchestrator, RunnerUnavailableError


def test_init() -> None:
    """초기화: cdp 는 None, hitl_log_path 는 기본 문자열이다."""
    o = Orchestrator()

    # cdp 는 지연 초기화라 초기엔 None 이어야 함.
    assert o.cdp is None
    # hitl_log_path 는 생성자 기본값(문자열)이어야 함.
    assert isinstance(o._hitl_log_path, str)
    assert o._hitl_log_path == "logs/hitl_requests.log"


def test_receive_handoff_no_runner() -> None:
    """runner=None 일 때 receive_handoff() 는 RunnerUnavailableError 를 발생한다."""
    o = Orchestrator()
    # 내부 속성 덮어쓰기로 runner 부재 상황 재현 (의존성 실패와 동일).
    o.runner = None

    handoff = Handoff(url="http://example.com", dom_snapshot="{}")

    # 실제 코드는 '' 반환이 아니라 예외 발생 — 그에 맞춰 검증.
    with pytest.raises(RunnerUnavailableError):
        o.receive_handoff(handoff)


def test_receive_hitl_log() -> None:
    """receive_hitl() 호출 시 인메모리 로그 및 file JSONL 에 기록된다."""
    # 임시 디렉토리 생성 후 그 안에 로그 파일 경로 지정 (테스트 후 정리).
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, "hitl_requests.log")

    try:
        o = Orchestrator(hitl_log_path=tmp_path)
        hitl = HITLRequest(url="u", reason="captcha")
        o.receive_hitl(hitl)

        # (a) 인메모리 로그 마지막 항목의 status 검증.
        assert o._hitl_log[-1]["status"] == "awaiting_human"
        assert o._hitl_log[-1]["reason"] == "captcha"

        # (b) file JSONL 에 "awaiting_human"·"captcha" 포함 검증.
        with open(tmp_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "awaiting_human" in content
        assert "captcha" in content

        # JSONL 1행 파싱 검증 (구조 무결성).
        line = content.strip().splitlines()[-1]
        record = json.loads(line)
        assert record["status"] == "awaiting_human"
        assert record["url"] == "u"
    finally:
        # 테스트 후 임시 파일/디렉토리 정리.
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.isdir(tmp_dir):
            os.rmdir(tmp_dir)


def test_pause_for_human_sets_awaiting() -> None:
    """pause_for_human(url) 호출 후 is_paused(url) 가 True 로 전환된다."""
    o = Orchestrator()
    url = "http://example.com/captcha"

    o.pause_for_human(url)

    # 일시정지 상태 머신이 "awaiting" 으로 기록되었는지 검증.
    assert o.is_paused(url) is True


def test_resume_clears_awaiting() -> None:
    """pause_for_human 후 resume(url) 하면 is_paused(url) 가 False 로 돌아온다."""
    o = Orchestrator()
    url = "http://example.com/captcha"

    o.pause_for_human(url)
    assert o.is_paused(url) is True

    o.resume(url)
    # 해결(resolved) 상태로 전환되어 대기 플래그가 내려갔는지 검증.
    assert o.is_paused(url) is False


def test_request_hitl_returns_hitl_request_and_logs() -> None:
    """request_hitl() 은 HITLRequest 를 반환하고 receive_hitl 로그에 기록된다.

    receive_hitl() 을 래핑하므로, 호출 결과가 인메모리 ``_hitl_log`` 에
    append 되는지로 실제 전달 경로를 검증한다.
    """
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, "hitl_requests.log")

    try:
        o = Orchestrator(hitl_log_path=tmp_path)
        url = "http://example.com/login"
        reason = "manual_review_needed"

        result = o.request_hitl(url, reason)

        # (a) 반환값은 HITLRequest 이며 필드가 올바르다.
        assert isinstance(result, HITLRequest)
        assert result.url == url
        assert result.reason == reason

        # (b) receive_hitl 경유로 _hitl_log 에 기록되었다.
        assert len(o._hitl_log) == 1
        assert o._hitl_log[-1]["url"] == url
        assert o._hitl_log[-1]["reason"] == reason
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.isdir(tmp_dir):
            os.rmdir(tmp_dir)
