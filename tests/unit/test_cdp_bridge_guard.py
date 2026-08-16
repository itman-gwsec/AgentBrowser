"""CDP 브리지 봇 탐지 사전 검증 테스트 (tests/unit/test_cdp_bridge_guard.py).

검증 대상(src/core/cdp_bridge.py):
    - CDPBridge.connect() 는 실제 크롬에 붙기 *전*에 봇 탐지 시그널을 사전
      검증한다:
        (a) attach 대상이 ``--enable-automation`` 플래그로 뜬 Chrome 인지 확인.
        (b) ``navigator.webdriver`` 가 true 인지 확인.
      둘 중 하나라도 양성이면 connect() 는 BotDetectionError 를 발생시켜,
      플래그가 묻은 세션에 에이전트가 붙는 것을 원천 차단한다 (IDEA.md R2).

테스트 방식:
    - 실제 Chrome 기동 금지. ``connect_over_cdp`` 를 모킹하여 page.evaluate
      반환값(puppeteer/chromedriver 흔적)을 주입한다.
    - (1) webdriver=true 인 페이지에 붙으려 하면 BotDetectionError.
    - (2) webdriver=false(깨끗한 headed Chrome)면 정상 attach 흐름 진입.

컨벤션: snake_case, 한국어 주석. pytest + unittest.mock.
"""

from __future__ import annotations

from unittest import mock

import pytest

from core.cdp_bridge import BotDetectionError, CDPBridge
from core.handoff import HITLRequest


def _patch_connect(target: CDPBridge, webdriver_value: bool) -> None:
    """connect_over_cdp 와 page.evaluate 를 모킹하여 웹드라이버 상태를 주입한다.

    실제 크롬/네트워크 없이 브리지 로직만 검증하기 위함.
    """
    fake_page = mock.MagicMock()
    fake_page.evaluate.return_value = webdriver_value

    fake_context = mock.MagicMock()
    fake_context.pages = [fake_page]

    fake_browser = mock.MagicMock()
    fake_browser.contexts = [fake_context]

    fake_p = mock.MagicMock()
    # connect() 는 sync_playwright().start() 를 호출하므로, start() 가 자기 자신을
    # 반환하도록 설정해야 self.p 가 fake_p 가 되어 하위 체인(fake_browser 등)이 전달된다.
    fake_p.start.return_value = fake_p
    fake_p.chromium.connect_over_cdp.return_value = fake_browser

    with mock.patch("playwright.sync_api.sync_playwright", return_value=fake_p):
        target.connect()


def test_connect_rejects_webdriver_true() -> None:
    """navigator.webdriver=true 이면 BotDetectionError 를 발생시킨다 (R2).

    pipe 로 자기 자신이 spawn 한 세션이 아닌, 외부/기존 세션(port transport,
    self_launched=False)에 붙을 때의 봇 탐지 차단 경로를 검증한다.
    """
    bridge = CDPBridge(port=9222, transport="port")
    with pytest.raises(BotDetectionError):
        _patch_connect(bridge, webdriver_value=True)


def test_connect_allows_webdriver_false() -> None:
    """navigator.webdriver=false(깨끗한 headed Chrome)면 정상 attach 한다.

    외부/기존 세션(port transport, self_launched=False)에 붙을 때의 정상 경로.
    """
    bridge = CDPBridge(port=9222, transport="port")
    # 예외 없이 진입해야 한다.
    _patch_connect(bridge, webdriver_value=False)
    assert bridge.page is not None


def _make_bridge_with_page(
    detected: bool, page_url: str = "http://example.com/captcha"
) -> CDPBridge:
    """page.evaluate 결과를 주입한 CDPBridge 를 생성한다 (실제 크롬 기동 금지).

    ``detect_and_request_hitl()`` 은 ``self.page`` 가 None 이면 조기 반환하므로,
    mock 페이지를 직접 주입해 탐지 경로만 검증한다.
    """
    bridge = CDPBridge(port=9222)
    fake_page = mock.MagicMock()
    fake_page.evaluate.return_value = detected
    fake_page.url = page_url
    bridge.page = fake_page
    return bridge


def test_detect_and_request_hitl_detected() -> None:
    """page.evaluate 가 True(캡차 흔적)를 반환하면 HITLRequest 를 반환한다."""
    bridge = _make_bridge_with_page(detected=True)

    result = bridge.detect_and_request_hitl()

    # 캡차 흔적 탐지 시 HITLRequest(captcha_detected) 반환.
    assert result is not None
    assert isinstance(result, HITLRequest)
    assert result.reason == "captcha_detected"
    assert result.url == "http://example.com/captcha"


def test_detect_and_request_hitl_not_detected() -> None:
    """page.evaluate 가 False(흔적 없음)를 반환하면 None 을 반환한다."""
    bridge = _make_bridge_with_page(detected=False)

    result = bridge.detect_and_request_hitl()

    # 흔적 미탐지 시 None 반환.
    assert result is None
