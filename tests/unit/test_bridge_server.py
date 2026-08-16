"""브릿지 서버 단위 테스트 (tests/unit/test_bridge_server.py).

검증 대상(src/core/bridge_server.py):
    - ``_handle_resume(body)`` 헬퍼: {url} 수신 → ``Orchestrator().resume(url)``
      호출 → ``(200, {"ok": True, "url": url})`` 반환.
    - url 누락 시 ``(400, {"error": "url required"})`` 반환 (resume 미호출).

테스트 방식 (사실, 검증 가능):
    - 실제 HTTP 서버 기동 없이 ``HandoffHandler`` 인스턴스를 직접 생성하고
      ``_handle_resume(body)`` 헬퍼를 호출하여 단위 검증한다.
    - ``Orchestrator`` 클래스는 모킹하여 실제 ``Runner``/``LLM`` 생성 경로를
      차단한다 (``Orchestrator()`` 생성 비용 회피 + 외부 네트워크 무호출).
    - 헬퍼가 실제로 ``Orchestrator().resume(url)`` 을 호출했음을 스파이로 명시 검증.

컨벤션: snake_case, 한국어 주석, 표준 라이브러리 + pytest + unittest.mock.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.bridge_server import HandoffHandler


def _make_handler() -> HandoffHandler:
    """최소한의 ``HandoffHandler`` 인스턴스를 생성한다 (서버/소켓 기동 없음).

    ``__new__`` 로 인스턴스만 확보하므로 ``__init__``(rfile/wfile/headers 의존)
    가 실행되지 않는다. 본 테스트는 I/O 가 없는 ``_handle_resume`` 만 호출한다.
    """
    return HandoffHandler.__new__(HandoffHandler)


def test_handle_resume_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """{url} 정상 수신 → Orchestrator().resume(url) 호출 + (200, ok) 반환."""
    # Orchestrator 클래스를 모킹: Orchestrator() → mock 인스턴스, .resume 을 기록.
    mock_instance = MagicMock()
    mock_class = MagicMock(return_value=mock_instance)
    monkeypatch.setattr("core.bridge_server.Orchestrator", mock_class)

    handler = _make_handler()
    status, body = handler._handle_resume({"url": "http://captcha.example.com"})

    # (1) 응답: 상태 200, 본문에 ok/url 포함.
    assert status == 200
    assert body == {"ok": True, "url": "http://captcha.example.com"}

    # (2) 실제 Orchestrator().resume(url) 이 1회 호출되었음을 명시 검증.
    mock_class.assert_called_once()
    mock_instance.resume.assert_called_once_with("http://captcha.example.com")


def test_handle_resume_missing_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """url 누락 → (400, {"error": "url required"}) 반환 + resume 미호출."""
    mock_instance = MagicMock()
    mock_class = MagicMock(return_value=mock_instance)
    monkeypatch.setattr("core.bridge_server.Orchestrator", mock_class)

    handler = _make_handler()
    status, body = handler._handle_resume({})

    assert status == 400
    assert body == {"error": "url required"}
    # url 누락 시 Orchestrator 생성/호출이 일절 없어야 함.
    mock_class.assert_not_called()
    mock_instance.resume.assert_not_called()
