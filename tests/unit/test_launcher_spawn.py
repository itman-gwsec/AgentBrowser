"""spawn_chrome_pipe 단위 테스트 — pass_fds 방식 검증 (실제 Chrome 미기동).

검증 목표:
    - 수정된 spawn_chrome_pipe 가 ``preexec_fn`` 없이 ``pass_fds=[3, 4]`` +
      ``close_fds=True``(기본) 로 Popen 을 호출하는지.
    - fd 3/4 예약번호와 부모 보관 fd(w_cmd/r_evt) 가 충돌하는 케이스(w_cmd==4)에서도
      예외 없이 기동 인자를 구성하는지.
    - Chrome 이 즉시 죽으면 최대 3회 재시도 후 RuntimeError 를 던지는지.
"""

from __future__ import annotations

import itertools
import os
import subprocess
from unittest import mock

import pytest

from core.launcher import (
    _CDP_PIPE_READ_FD,
    _CDP_PIPE_WRITE_FD,
    CHROME_PATH,
    spawn_chrome_pipe,
)


def _patch_spawn(monkeypatch: pytest.MonkeyPatch, pipe_pairs, poll_values):
    """os.pipe / os.dup / os.dup2 / os.close / time.sleep 를 부작용 없이 치환하고,
    Popen 을 가로채 kwargs 를 captured 에 기록한다. poll_values 는 시도별 poll() 반환값.
    """
    pair_iter = itertools.cycle(pipe_pairs)
    monkeypatch.setattr(os, "pipe", lambda: next(pair_iter))
    monkeypatch.setattr(os, "dup", lambda fd: 999)  # 충돌 회피 relocation 용 dummy
    monkeypatch.setattr(os, "dup2", lambda a, b: None)
    monkeypatch.setattr(os, "close", lambda fd: None)
    monkeypatch.setattr("core.launcher.time.sleep", lambda *a, **k: None)

    captured: dict = {}
    poll_iter = itertools.cycle(poll_values)

    def fake_popen(*args, **kwargs):
        captured.clear()
        captured.update(kwargs)
        fake = mock.MagicMock()
        fake.poll.return_value = next(poll_iter)
        fake.returncode = 13
        captured["_proc"] = fake
        return fake

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return captured


def test_spawn_uses_pass_fds_not_preexec(monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 기동: pass_fds=[3,4], preexec_fn=None, close_fds=True."""
    if not os.path.exists(CHROME_PATH):
        monkeypatch.setattr(
            os.path, "exists",
            lambda p: True if p == CHROME_PATH else os.path.exists(p),
        )
    captured = _patch_spawn(monkeypatch, pipe_pairs=[(10, 11), (12, 13)], poll_values=[None])

    proc, w_cmd, r_evt = spawn_chrome_pipe(profile_name="default")

    assert proc is captured["_proc"]
    assert captured.get("pass_fds") == [_CDP_PIPE_READ_FD, _CDP_PIPE_WRITE_FD]
    # 핵심: preexec_fn 조합(이전 macOS 크래시 원인) 은 더 이상 사용하지 않는다.
    assert captured.get("preexec_fn") is None
    # close_fds=False(이전 코드) 가 아니어야 함 — 기본 True 유지.
    assert captured.get("close_fds", True) is True
    assert captured.get("start_new_session") is True
    # 부모 보관 fd 가 반환된다.
    assert isinstance(w_cmd, int) and isinstance(r_evt, int)


def test_spawn_fd_collision_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """w_cmd==4(예약번호와 충돌) 케이스에서도 예외 없이 pass_fds 로 기동되는지."""
    if not os.path.exists(CHROME_PATH):
        monkeypatch.setattr(
            os.path, "exists",
            lambda p: True if p == CHROME_PATH else os.path.exists(p),
        )
    # r_cmd=10, w_cmd=4(=예약 WRITE) ; r_evt=12, w_evt=13
    captured = _patch_spawn(monkeypatch, pipe_pairs=[(10, 4), (12, 13)], poll_values=[None])

    proc, w_cmd, _r_evt = spawn_chrome_pipe(profile_name="default")

    assert proc is captured["_proc"]
    assert captured.get("pass_fds") == [_CDP_PIPE_READ_FD, _CDP_PIPE_WRITE_FD]
    assert captured.get("preexec_fn") is None
    # relocation 으로 w_cmd(=4) 가 다른 fd 로 옮겨졌는지(꼬이지 않음) — 4 가 아니어야.
    assert w_cmd != _CDP_PIPE_WRITE_FD


def test_spawn_retries_on_immediate_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chrome 이 즉시 죽으면 3회 재시도 후 RuntimeError(exit=13) 를 던진다."""
    if not os.path.exists(CHROME_PATH):
        monkeypatch.setattr(
            os.path, "exists",
            lambda p: True if p == CHROME_PATH else os.path.exists(p),
        )
    # 매 시도 poll() 이 즉시 13 을 반환 → 3회 후 실패.
    captured = _patch_spawn(monkeypatch, pipe_pairs=[(10, 11), (12, 13)], poll_values=[13])

    with pytest.raises(RuntimeError) as exc:
        spawn_chrome_pipe(profile_name="default")

    assert "exit=13" in str(exc.value)
    # 재시도마다 동일하게 pass_fds 방식 사용.
    assert captured.get("pass_fds") == [_CDP_PIPE_READ_FD, _CDP_PIPE_WRITE_FD]
