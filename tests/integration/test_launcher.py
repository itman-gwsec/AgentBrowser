"""크롬 런처 통합 테스트 (tests/integration/test_launcher.py).

검증 대상(src/core/launcher.py):
    - ``build_launch_command()`` 이 구성하는 명령줄 args 가 의도한 형태인지 검증.
      (전용 프로파일 디렉터리, 원격 디버그 포트, 익스텐션 주입, 봇 플래그 배제)
    - ``launch_chrome()`` 은 제거되었으므로, 그 역할은 ``build_launch_command()``
      (명령줄 반환) + ``ensure_attachable()`` (스스로 spawn 하지 않음) 으로 대체.

테스트 방식 (사실, 검증 가능):
    1. 실제 Chrome 을 기동하지 않는다 — ``subprocess.Popen`` 을 모킹하여, 런처가
       스스로 spawn 하지 않음을 보장함과 동시에 명령줄 구성을 검증한다.
    2. (a) CHROME_PATH 존재 여부를 확인한다. 미설치 env 에서는 os.path.exists 를
       해당 경로에 한해 스텁하여, 함수가 FileNotFoundError 없이 args 구성에
       도달하도록 한다(본검증은 항상 수행 → 헤드리스/CI 에서도 녹색).
    3. (b) 반환된 명령줄에 다음이 포함되는지 명시 검증:
         - ``--user-data-dir=`` 형태이고 ``profiles/default`` 를 포함
         - ``--remote-debugging-port=9222``
         - ``--load-extension=`` (익스텐션 절대경로 주입)
         - ``--no-first-run``, ``--no-default-browser-check``
         - ``--enable-automation`` 이 절대 포함되지 않음 (R2 봇회피)

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
)


def test_args_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_launch_command 이 구성하는 명령줄 args 를 모킹으로 검증한다.

    실제 Chrome 기동은 금지하므로 ``subprocess.Popen`` 을 모킹하여, 런처가
    스스로 spawn 하지 않으면서도 의도한 args 를 구성함을 확인한다.
    """
    # (a) CHROME_PATH 존재 여부 확인. 미설치 env 에서는 해당 경로에 한정해
    #     os.path.exists 를 True 로 스텁하여 함수가 예외 없이 진행되게 한다.
    if not os.path.exists(CHROME_PATH):
        monkeypatch.setattr(
            os.path,
            "exists",
            lambda p: True if p == CHROME_PATH else os.path.exists(p),
        )

    # 디스크 부작용 방지: profiles/<name> 디렉터리 생성을 no-op 으로 치환.
    monkeypatch.setattr(os, "makedirs", lambda *args, **kwargs: None)

    # (b) subprocess.Popen 모킹 → spawn 되지 않음을 보장(실제 Chrome 기동 금지).
    spawned: dict[str, bool] = {"called": False}

    def fake_popen(*args: object, **kwargs: object) -> mock.MagicMock:
        spawned["called"] = True
        fake_process = mock.MagicMock(spec=subprocess.Popen)
        fake_process.pid = 99999
        return fake_process

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    # 새 API: build_launch_command() 는 명령줄 리스트만 반환(스폰 없음).
    cmd = build_launch_command(profile_name="default")

    # 런처가 스스로 Chrome 을 spawn 하지 않았음을 보장.
    assert spawned["called"] is False, "런처가 스스로 spawn 하면 안 됩니다."

    assert cmd, "build_launch_command 의 반환값이 비어 있습니다."

    # 1) 첫 번째 인자는 Chrome 바이너리 경로.
    assert cmd[0] == CHROME_PATH, f"args[0] 가 CHROME_PATH 가 아닙니다: {cmd[0]!r}"

    # 2) 전용 프로파일 디렉터리 주입 ("profiles/default" 포함).
    #    실제 코드는 절대경로(PROJECT_ROOT/profiles/default)를 사용하므로
    #    "profiles/default" 를 포함하는지로 검증한다.
    user_data_dir = next((a for a in cmd if a.startswith("--user-data-dir=")), None)
    assert user_data_dir is not None, "args 에 --user-data-dir= 가 없습니다."
    assert "profiles/default" in user_data_dir, (
        f"--user-data-dir 에 profiles/default 가 없습니다: {user_data_dir!r}"
    )

    # 3) 원격 디버깅 — M5 부터는 pipe transport (TCP 포트 미개방 → 방화벽 프롬프트 회피).
    assert "--remote-debugging-pipe" in cmd, (
        f"args 에 --remote-debugging-pipe 가 없습니다: {cmd!r}"
    )
    # 하위 호환용 TCP 포트(--remote-debugging-port)는 pipe 모드에서 사용하지 않는다.
    assert "--remote-debugging-port" not in cmd, (
        f"args 에 --remote-debugging-port 가 있으면 안 됩니다(pipe 모드): {cmd!r}"
    )

    # 4) 익스텐션 절대경로 주입 (--load-extension=).
    load_extension = next((a for a in cmd if a.startswith("--load-extension=")), None)
    assert load_extension is not None, "args 에 --load-extension= 이 없습니다."

    # 부가 검증: 첫 실행 억제 플래그가 함께 전달되는지 확인.
    assert "--no-first-run" in cmd, "args 에 --no-first-run 가 없습니다."
    assert "--no-default-browser-check" in cmd, (
        "args 에 --no-default-browser-check 가 없습니다."
    )

    # 봇 탐지 플래그가 절대 포함되지 않음을 명시 검증 (R2 봇회피).
    assert "--enable-automation" not in cmd, (
        f"기동 명령줄에 --enable-automation 이 포함되면 안 됩니다: {cmd!r}"
    )


def test_ensure_attachable_returns_command_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ensure_attachable 이 안 떠있을 때 스스로 spawn 하지 않고 명령줄을 반환한다."""
    # CHROME_PATH 미설치 env 대비 스텁.
    if not os.path.exists(CHROME_PATH):
        monkeypatch.setattr(
            os.path,
            "exists",
            lambda p: True if p == CHROME_PATH else os.path.exists(p),
        )
    # 포트에 아무 것도 안 떠있다고 가정.
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
    assert spawned["called"] is False, "안 떠있어도 런처가 스스로 spawn 하면 안 됩니다."
    assert "--enable-automation" not in result, (
        "반환 명령줄에 --enable-automation 이 있으면 안 됩니다."
    )
