"""M5 단위 테스트 (tests/unit/test_launcher.py).

검증 대상:
    - ``core.launcher.build_launch_command`` 가 ``--remote-debugging-port`` 를
      **포함하지 않고** ``--remote-debugging-pipe`` 를 **포함**하는지 (M5 핵심).
    - ``--enable-automation`` 미포함 (R2 봇회피 유지).
    - 포커스/백그라운드 격리 플래그 포함.
    - ``core.cdp_bridge.CDPBridge.connect`` 가 포트 URL(``http://127.0.0.1:<port>``)
      이 아닌 **pipe 방식(``ws://...`` 브리지)** 으로 붙는지 (Mock 검증).

컨벤션: snake_case, 한국어 주석. pytest + unittest.mock.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from core.cdp_bridge import CDPBridge
from core.launcher import (
    _FOCUS_ISOLATION_FLAGS,
    CHROME_PATH,
    build_launch_command,
)


def _stub_chrome_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """미설치 env 에서도 테스트가 녹색이 되도록 CHROME_PATH 를 스텁."""
    if not os.path.exists(CHROME_PATH):
        monkeypatch.setattr(
            os.path,
            "exists",
            lambda p: True if p == CHROME_PATH else os.path.exists(p),
        )


def test_build_launch_command_uses_pipe_not_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """M5: --remote-debugging-port 가 없고 --remote-debugging-pipe 가 있어야 한다."""
    _stub_chrome_path(monkeypatch)
    cmd = build_launch_command(profile_name="default")

    # 포트 미개방 → macOS 방화벽 "리모트 디버깅 허용" 프롬프트 회피 (Q5 port_open:false).
    assert "--remote-debugging-port" not in cmd, (
        f"--remote-debugging-port 가 있으면 안 됩니다(M5 는 pipe): {cmd!r}"
    )
    assert "--remote-debugging-pipe" in cmd, (
        f"--remote-debugging-pipe 가 없으면 안 됩니다(M5): {cmd!r}"
    )


def test_build_launch_command_no_enable_automation(monkeypatch: pytest.MonkeyPatch) -> None:
    """기동 명령줄에 --enable-automation 이 포함되지 않아야 한다 (R2 봇회피)."""
    _stub_chrome_path(monkeypatch)
    cmd = build_launch_command(profile_name="default")
    assert "--enable-automation" not in cmd, (
        f"기동 명령줄에 --enable-automation 이 포함되면 안 됩니다: {cmd!r}"
    )
    # 기본 headed Chrome 기동 최소 플래그 유지.
    assert any(a == CHROME_PATH for a in cmd), "Chrome 바이너리가 명령줄에 없습니다."
    assert any(a.startswith("--user-data-dir=") for a in cmd), "전용 프로파일이 없습니다."


def test_build_launch_command_has_focus_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """포커스/백그라운드 격리 플래그가 포함되어야 한다 (사용자 작업과 겹치지 않게)."""
    _stub_chrome_path(monkeypatch)
    cmd = build_launch_command(profile_name="default")
    for flag in _FOCUS_ISOLATION_FLAGS:
        assert flag in cmd, f"포커스 격리 플래그가 누락되었습니다: {flag}"


def test_cdp_bridge_connect_uses_pipe_not_port_url() -> None:
    """CDPBridge.connect 가 포트 URL 이 아닌 pipe(ws://) 방식으로 붙는지 단언(Mock).

    spawn_chrome_pipe 로 Chrome 을 띄우고 PipeWebSocketBridge 로 ws:// 엔드포인트를
    만들며, 최종 ``connect_over_cdp`` 에 전달되는 URL 이 ``ws://`` 스킴이어야 한다
    (``http://127.0.0.1:<port>`` 가 아니어야 함).
    """
    # spawn_chrome_pipe 는 실제 Chrome 을 띄우므로 모킹. (proc, write_fd, read_fd)
    fake_proc = mock.MagicMock()
    fake_proc.poll.return_value = None  # 살아있다고 가정

    with mock.patch(
        "core.cdp_bridge.spawn_chrome_pipe", return_value=(fake_proc, 7, 8)
    ), mock.patch("core.cdp_bridge._PipeWebSocketBridge") as MockBridge, mock.patch(
        "playwright.sync_api.sync_playwright"
    ) as mock_pw:
        # 브리지 인스턴스는 ws_url 속성만 제공하면 된다.
        bridge_inst = mock.MagicMock()
        bridge_inst.ws_url = "ws://127.0.0.1:54321"
        bridge_inst.wait_until_ready.return_value = True
        MockBridge.return_value = bridge_inst

        fake_page = mock.MagicMock()
        # pipe artifact 로 webdriver=true 가 나와도 self_launched=True 이므로 진행.
        fake_page.evaluate.return_value = True
        fake_context = mock.MagicMock()
        fake_context.pages = [fake_page]
        fake_browser = mock.MagicMock()
        fake_browser.contexts = [fake_context]

        fake_p = mock.MagicMock()
        fake_p.start.return_value = fake_p
        fake_p.chromium.connect_over_cdp.return_value = fake_browser

        captured = {}

        def capture_connect(url):
            captured["url"] = url
            return fake_browser

        fake_p.chromium.connect_over_cdp.side_effect = capture_connect
        mock_pw.return_value = fake_p

        bridge = CDPBridge(profile_name="default", transport="pipe")
        bridge.connect()

        # 1) 포트 URL 이 아니어야 한다.
        assert captured["url"] != "http://127.0.0.1:9222", (
            "pipe 모드인데 포트 URL 로 붙었습니다."
        )
        # 2) ws:// 스킴(pipe 브리지) 이어야 한다.
        assert captured["url"].startswith("ws://"), (
            f"connect_over_cdp 에 전달된 URL 이 ws:// 가 아닙니다: {captured['url']!r}"
        )
        # 3) spawn_chrome_pipe + PipeWebSocketBridge 가 호출되어 pipe 기동/브리지되었는지.
        assert MockBridge.called, "pipe 브리지가 생성되지 않았습니다."
