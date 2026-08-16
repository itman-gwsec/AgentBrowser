"""런처 attach 전용 모드 통합 테스트 (tests/integration/test_launcher_attach.py).

검증 대상(src/core/launcher.py):
    - launch_chrome() 이 더 이상 직접 Chrome 을 spawn 하지 않는다.
      (spawn 시 Playwright/CDP 가 --enable-automation 플래그를 주입하여
       "Chrome 이 자동화된 테스트 소프트웨어에 의해 제어되고 있습니다"
       인포바 + navigator.webdriver=true 봇 탐지 시그널이 노출됨 — R2 위반)
    - 대신 attach 전용 모드를 제공한다:
        (a) is_chrome_running(profile_name): pipe 모드(비네트워크)이므로 포트 대신
            프로파일 기반 pgrep 로 해당 Chrome 프로세스 존재 여부를 확인.
        (b) build_launch_command(...): --enable-automation 이 *포함되지 않은*
            headed Chrome 기동 명령줄을 반환(인간이 직접 실행).
        (c) ensure_attachable(...): 떠있으면 True, 없으면 기동 명령줄을
            반환(스스로 spawn 하지 않음 — 중요).

테스트 방식 (사실, 검증 가능):
    1. 실제 Chrome 기동은 금지. subprocess.Popen 모킹으로 args 만 캡처.
    2. build_launch_command() 반환 문자열에 --enable-automation 이 없음을 명시 검증.
    3. ensure_attachable() 이 스스로 spawn 하지 않고 명령줄을 반환함을 검증.

컨벤션: snake_case, 한국어 주석. 표준 라이브러리 + pytest + unittest.mock.
"""

from __future__ import annotations

import os
import subprocess
from unittest import mock

import pytest

from core.launcher import (
    CHROME_PATH,
    build_launch_command,
    ensure_attachable,
    is_chrome_running,
)


def _stub_chrome_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """CHROME_PATH 가 미설치 env 에서도 테스트가 녹색이 되도록 스텁한다."""
    if not os.path.exists(CHROME_PATH):
        monkeypatch.setattr(
            os.path,
            "exists",
            lambda p: True if p == CHROME_PATH else os.path.exists(p),
        )


def test_build_launch_command_has_no_enable_automation() -> None:
    """기동 명령줄에 --enable-automation 이 포함되지 않아야 한다 (R2 봇회피)."""
    cmd = build_launch_command(profile_name="default")
    assert isinstance(cmd, list)
    assert "--enable-automation" not in cmd, (
        f"기동 명령줄에 --enable-automation 이 포함되면 안 됩니다: {cmd!r}"
    )
    # 기본 headed Chrome 기동에 필요한 최소 플래그는 유지.
    assert any(a == CHROME_PATH for a in cmd), "Chrome 바이너리가 명령줄에 없습니다."
    assert any(a.startswith("--user-data-dir=") for a in cmd), "전용 프로파일이 없습니다."
    # M5: TCP 포트 대신 pipe transport 사용 (방화벽 프롬프트 회피, lsof -i:9222 = null).
    assert any(a == "--remote-debugging-pipe" for a in cmd), "pipe transport 가 없습니다."
    assert not any(
        a.startswith("--remote-debugging-port=") for a in cmd
    ), "M5 에서는 포트를 열면 안 됩니다(pipe 전용)."


def test_build_launch_command_includes_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    """기동 명령줄에 익스텐션 절대경로가 주입된다."""
    _stub_chrome_path(monkeypatch)
    cmd = build_launch_command(profile_name="e2e")
    load_extension = next((a for a in cmd if a.startswith("--load-extension=")), None)
    assert load_extension is not None, "명령줄에 --load-extension= 이 없습니다."


def test_ensure_attachable_spawns_when_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """이미 떠있으면 스스로 spawn 하지 않고 True 를 반환한다."""
    _stub_chrome_path(monkeypatch)
    monkeypatch.setattr("core.launcher.is_chrome_running", lambda port: True)

    spawned: dict[str, bool] = {"called": False}

    def fake_popen(*args: object, **kwargs: object) -> mock.MagicMock:
        spawned["called"] = True
        fake_process = mock.MagicMock(spec=subprocess.Popen)
        fake_process.pid = 99999
        return fake_process

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    result = ensure_attachable()
    assert result is True, "이미 떠있는데 False 를 반환했습니다."
    assert spawned["called"] is False, "이미 떠있는데 스스로 spawn 하면 안 됩니다."


def test_ensure_attachable_returns_command_when_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """안 떠있으면 스스로 spawn 하지 않고 기동 명령줄을 반환한다."""
    _stub_chrome_path(monkeypatch)
    monkeypatch.setattr("core.launcher.is_chrome_running", lambda port: False)

    spawned: dict[str, bool] = {"called": False}

    def fake_popen(*args: object, **kwargs: object) -> mock.MagicMock:
        spawned["called"] = True
        fake_process = mock.MagicMock(spec=subprocess.Popen)
        fake_process.pid = 99999
        return fake_process

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    result = ensure_attachable()
    assert isinstance(result, list), "안 떠있을 때 기동 명령줄(list)을 반환해야 합니다."
    assert spawned["called"] is False, (
        "안 떠있어도 런처가 스스로 spawn 하면 안 됩니다(인포바/플래그 노출)."
    )
    assert "--enable-automation" not in result, (
        "반환 명령줄에 --enable-automation 이 있으면 안 됩니다."
    )


def test_is_chrome_running_probes_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """프로파일명 기반 pgrep 매칭 여부로 True/False 를 반환한다 (M5 pipe 모드).

    M5 부터는 원격 디버깅이 pipe(비네트워크)이므로 포트 프로브 대신 프로세스
    존재 여부(pgrep)로 판단한다. ``lsof -i:<port>`` 는 항상 null 이다.
    """

    class _Proc:
        def __init__(self, rc: int, out: bytes = b"") -> None:
            self.returncode = rc
            self.stdout = out

    # (1) 매칭되는 프로세스가 있으면 True.
    monkeypatch.setattr(
        "core.launcher.subprocess.run",
        lambda *a, **k: _Proc(0, b"12345\n"),
    )
    assert is_chrome_running(profile_name="e2e") is True

    # (2) 매칭 프로세스가 없으면 False.
    monkeypatch.setattr(
        "core.launcher.subprocess.run",
        lambda *a, **k: _Proc(1, b""),
    )
    assert is_chrome_running(profile_name="e2e") is False
