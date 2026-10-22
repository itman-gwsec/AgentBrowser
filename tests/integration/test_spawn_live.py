"""spawn_chrome_pipe 실제 기동 통합 테스트 (AGENTBROWSER_LIVE=1 일 때만).

실제 Chrome 을 pipe 모드로 기동하고 CDP 파이프(fd 3/4) 로 핸드셰이크하여 다음을 검증:
    - Chrome 이 exit=0 으로 살아있는지 (proc.poll() is None)
    - navigator.webdriver === false (봇회피 transport artifact 가 아님을 확인)
    - CDP 명령/응답 라운드트립 성공 (Runtime.evaluate → 1+1 == 2)

참고: 구글 실제 검색은 수행하지 않는다(작업 금지). pipe transport 가 실제로
동작함을 CDP 라운드트립으로 증명한다.
"""

from __future__ import annotations

import contextlib
import json
import os
import select
import time

import pytest

from core.launcher import CHROME_PATH, spawn_chrome_pipe

LIVE = os.environ.get("AGENTBROWSER_LIVE") == "1"

pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="AGENTBROWSER_LIVE=1 이 필요 (실제 Chrome 기동)",
)


def _send(fd: int, msg: str) -> None:
    os.write(fd, (msg + "\x00").encode())


def _read_nul_msg(fd: int, timeout: float = 8.0) -> str:
    """NUL(\x00) 구분 CDP JSON 메시지 하나를 읽는다."""
    buf = b""
    while b"\x00" not in buf:
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            raise TimeoutError("CDP pipe response timeout")  # noqa: TRY003
        chunk = os.read(fd, 65536)
        if not chunk:
            raise EOFError("CDP pipe closed")  # noqa: TRY003
        buf += chunk
    return buf.split(b"\x00")[0].decode()


def _wait_response(fd: int, msg_id: int, timeout: float = 8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = _read_nul_msg(fd, timeout=max(0.5, deadline - time.time()))
        try:
            obj = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            continue
        if obj.get("id") == msg_id:
            return obj
    raise TimeoutError(f"CDP response id={msg_id} not received")  # noqa: TRY003


def test_spawn_pipe_live_webdriver_false_and_roundtrip() -> None:
    assert os.path.exists(CHROME_PATH), f"Chrome 없음: {CHROME_PATH}"

    proc, w_cmd, r_evt = spawn_chrome_pipe(profile_name="live_debug")
    try:
        assert proc.poll() is None, "Chrome 이 pipe 모드로 기동되지 않음 (exit!=0)"

        # Runtime.enable 후 navigator.webdriver 평가.
        _send(w_cmd, '{"id":1,"method":"Runtime.enable"}')
        _send(
            w_cmd,
            '{"id":2,"method":"Runtime.evaluate",'
            '"params":{"expression":"navigator.webdriver"}}',
        )
        resp2 = _wait_response(r_evt, 2)
        webdriver_val = resp2["result"]["result"]["value"]
        assert webdriver_val is False, f"navigator.webdriver != false: {webdriver_val!r}"

        # CDP 라운드트립 성공 증명: 1+1 == 2.
        _send(
            w_cmd,
            '{"id":3,"method":"Runtime.evaluate",'
            '"params":{"expression":"1+1"}}',
        )
        resp3 = _wait_response(r_evt, 3)
        assert resp3["result"]["result"]["value"] == 2
    finally:
        proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)
