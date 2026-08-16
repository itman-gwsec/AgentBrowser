"""BrowserSession.ensure_alive() 단위 테스트 (TDD — RED→GREEN).

검증 대상(src/core/session.py):
    - ``BrowserSession.ensure_alive()`` 는 on-demand 크롬 생존 확인 + 자동복구를
      수행한다 (M5 pipe 모드):
        1) 기존 ``self.bridge`` 가 있고 ``is_chrome_running(profile)`` 이면
           재사용(재접속 없음)하여 반환.
        2) 그렇지 않으면 ``CDPBridge(transport="pipe")`` 를 새로 생성하고
           ``connect()`` 를 호출한다. connect() 내부에서 런처가 Chrome 을
           직접 pipe spawn 하므로, 별도의 ``subprocess.Popen``/``build_launch_command``
           경로는 사용하지 않는다.
        3) connect() 실패 시 명확한 예외(``ChromeNotRecoverableError``) 발생.

테스트 방식:
    - 실제 Chrome 기동은 금지하므로 ``CDPBridge`` 를 모킹한다.
    - ``is_chrome_running`` / ``CDPBridge`` 를 모킹하여 각 분기별 호출 여부를
      단언한다.
    - 런처/브리지가 스스로 spawn 하더라도 ``--enable-automation`` 을 절대 넣지
      않으므로 봇 탐지 시그널이 유입되지 않는다 (IDEA.md R2).

컨벤션: snake_case, 한국어 주석. 표준 라이브러리 + pytest + unittest.mock.
"""

from __future__ import annotations

import pytest

from core.session import BrowserSession, ChromeNotRecoverableError


def _fake_bridge_factory(connected_marker: dict, connect_raises: Exception | None = None) -> type:
    """CDPBridge 를 대체할 페이크 클래스(connect 시 핸들 세팅, 실패 시 예외)."""

    class FakeBridge:
        def __init__(self, *args: object, **kwargs: object) -> None:
            # session.ensure_alive 가 전달하는 (port/profile_name/extension_dir/transport)
            # 키워드 인자를 그대로 받는다 (실제 spawn 은 하지 않음).
            self.port = kwargs.get("port")
            self.profile_name = kwargs.get("profile_name")
            self.transport = kwargs.get("transport")
            self.connected = False

        def connect(self) -> None:
            if connect_raises is not None:
                raise connect_raises
            # connect 가 호출되었음을 기록하고 핸들 세팅(attach 모방).
            connected_marker["connect_called"] = True
            self.connected = True
            self.browser = object()
            self.context = object()
            self.page = object()

    return FakeBridge


def test_ensure_alive_creates_and_connects_when_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """없는 브리지(죽은 상태)에서는 항상 새 CDPBridge(pipe spawn) 를 생성+connect 한다."""
    connected: dict[str, bool] = {"connect_called": False}
    fake_bridge = _fake_bridge_factory(connected)
    monkeypatch.setattr("core.session.CDPBridge", fake_bridge)
    # 떠있지 않음 → 새로 spawn+attach 경로.
    monkeypatch.setattr("core.session.is_chrome_running", lambda profile: False)

    session = BrowserSession()
    bridge = session.ensure_alive()

    assert connected["connect_called"] is True, (
        "fresh session 은 CDPBridge.connect()(pipe spawn) 을 호출해야 합니다."
    )
    assert bridge is not None


def test_ensure_alive_reuses_existing_bridge_when_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """이미 살아있는 기존 브리지는 재접속 없이 재사용한다 (추가 pipe spawn 없음)."""
    connected: dict[str, bool] = {"connect_called": False}
    fake_bridge = _fake_bridge_factory(connected)
    monkeypatch.setattr("core.session.CDPBridge", fake_bridge)
    monkeypatch.setattr("core.session.is_chrome_running", lambda profile: True)

    session = BrowserSession()
    # 사전에 attach 된 브리지가 있다고 가정.
    existing = fake_bridge()
    session.bridge = existing

    result = session.ensure_alive()

    assert result is existing, "alive 브리지는 동일 인스턴스를 반환해야 합니다."
    assert connected["connect_called"] is False, (
        "alive 브리지는 재접속(connect) 하면 안 됩니다."
    )


def test_ensure_alive_second_call_reuses_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """두 번째 ensure_alive() 는 살아있는 브리지를 재사용(재접속 미수행)한다."""
    connected: dict[str, bool] = {"connect_called": False}
    fake_bridge = _fake_bridge_factory(connected)
    monkeypatch.setattr("core.session.CDPBridge", fake_bridge)
    monkeypatch.setattr("core.session.is_chrome_running", lambda profile: True)

    session = BrowserSession()
    bridge1 = session.ensure_alive()
    # 첫 attach 기록 초기화 후 두 번째 호출.
    connected["connect_called"] = False
    bridge2 = session.ensure_alive()

    # 두 번째는 spawn/connect 없이 기존 브리지를 그대로 반환.
    assert connected["connect_called"] is False, (
        "브리지가 살아있으면 재connect 하면 안 됩니다."
    )
    assert bridge1 is bridge2, "같은 브리지 인스턴스를 재사용해야 합니다."


def test_ensure_alive_raises_when_unrecoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """connect() 가 실패하면 명확한 ChromeNotRecoverableError 로 전파된다."""
    fake_bridge = _fake_bridge_factory({}, connect_raises=RuntimeError("spawn boom"))
    monkeypatch.setattr("core.session.CDPBridge", fake_bridge)
    monkeypatch.setattr("core.session.is_chrome_running", lambda profile: False)

    session = BrowserSession(startup_timeout_s=1)
    with pytest.raises(ChromeNotRecoverableError):
        session.ensure_alive()
