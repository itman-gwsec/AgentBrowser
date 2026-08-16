"""브라우저 세션 (on-demand 크롬 생존 확인 + 자동복구).

검색/제어 수행 **직전**에 크롬 인스턴스가 실제로 떠있는지 확인하고, 죽어 있으면
자동으로 기동(복구)한 뒤 CDP 로 attach 하는 래퍼다.

M5 변경 (2026-08-16):
- 기동은 pipe 모드(``--remote-debugging-pipe``) 를 사용한다. 포트를 열지 않으므로
  macOS 방화벽 "리모트 디버깅 허용" 프롬프트가 발생하지 않는다.
- pipe FD 는 별도 프로세스가 물려받을 수 없으므로, CDPBridge 가 Chrome 을 직접
  spawn 하고 FD 를 소유한다(``start_new_session`` 으로 독립 생존).
- 생존 확인은 ``is_chrome_running(profile_name)``(pgrep) 로 수행한다.
- 런처/브리지가 스스로 spawn 하더라도 ``--enable-automation`` 을 절대 넣지 않으므로
  봇 탐지 시그널이 유입되지 않는다 (IDEA.md R2). attach 후 ``CDPBridge.connect()``
  가 still ``webdriver=true`` 를 사전 검증한다 (pipe artifact 는 허용 — R2 이중 방어).
- 익스텐션 JS 수정은 절대 하지 않는다. 복구 기동 시에도 동일
  ``--load-extension`` 경로를 사용한다.
"""

from __future__ import annotations

import logging

from core.cdp_bridge import CDPBridge
from core.launcher import is_chrome_running

logger = logging.getLogger(__name__)

# CDP 엔드포인트 기동 대기 최대 시간(초) 및 폴링 간격(초) 기본값.
_STARTUP_TIMEOUT_S: float = 30.0


class ChromeNotRecoverableError(Exception):
    """ensure_alive() 가 Chrome 을 자동 복구하지 못했을 때 발생한다.

    spawn 은 시도했으나 CDP 엔드포인트가 타임아웃 내에 뜨지 않거나,
    기동 자체가 실패한 경우다.
    """


class BrowserSession:
    """on-demand 크롬 생존 확인 + 자동복구 세션 래퍼.

    ``ensure_alive()`` 는 검색/제어 직전에 호출하며, 죽은 인스턴스를
    자동으로 복구한 뒤 재사용 가능한 ``CDPBridge`` 를 반환한다.
    """

    def __init__(
        self,
        port: int = 9222,
        profile_name: str = "default",
        extension_dir: str = "src/extension",
        startup_timeout_s: float = _STARTUP_TIMEOUT_S,
        transport: str = "pipe",
    ) -> None:
        """포트/프로파일/익스텐션/타임아웃/transport 를 보관한다.

        Args:
            port: 하위 호환용 포트 (pipe transport 에선 미사용).
            profile_name: ``profiles/<name>`` 전용 프로파일 이름.
            extension_dir: 프로젝트 루트 기준 익스텐션 디렉터리(상대경로).
            startup_timeout_s: 기동 후 CDP 엔드포인트 응답 대기 최대(초).
            transport: ``"pipe"``(기본) 또는 ``"port"``.
        """
        self.port: int = port
        self.profile_name: str = profile_name
        self.extension_dir: str = extension_dir
        self.startup_timeout_s: float = startup_timeout_s
        self.transport: str = transport
        # 지연 연결되는 런타임 브리지 핸들 (ensure_alive 에서 채워짐).
        self.bridge: CDPBridge | None = None

    def ensure_alive(self) -> CDPBridge:
        """크롬 생존을 확인하고, 죽었으면 자동복구한 뒤 ``CDPBridge`` 를 반환한다.

        Returns:
            attach(또는 복구 후 attach)된 ``CDPBridge`` 인스턴스.

        Raises:
            ChromeNotRecoverableError: 기동했으나 CDP 엔드포인트가 타임아웃 내에
                뜨지 않거나 기동 자체가 실패한 경우.
            BotDetectionError: attach 대상에 봇 탐지 시그널이 감지된 경우
                (CDPBridge.connect 가 전파 — R2 이중 방어).
        """
        # 기존 브리지가 살아있으면 그대로 재사용 (기존 page/context 보존).
        if self.bridge is not None and self._is_bridge_alive():
            logger.info("기존 브리지 재사용 (profile=%s)", self.profile_name)
            return self.bridge

        # 떠있지 않으면(또는 보유 브리지 없으면) pipe 로 spawn+attach.
        logger.info(
            "Chrome ensure_alive — pipe spawn/attach 시도 (profile=%s)", self.profile_name
        )
        self.bridge = CDPBridge(
            port=self.port,
            profile_name=self.profile_name,
            extension_dir=self.extension_dir,
            transport=self.transport,
        )
        try:
            self.bridge.connect()
        except Exception as exc:
            self.bridge = None
            raise ChromeNotRecoverableError(  # noqa: TRY003
                f"Chrome pipe 기동/attach 실패 (profile={self.profile_name}): {exc}"
            ) from exc
        logger.info("Chrome 자동복구 완료 — attach 성공 (profile=%s)", self.profile_name)
        return self.bridge

    def _is_bridge_alive(self) -> bool:
        """보유 브리지의 연결이 유효한지(전용 프로파일 프로세스 존재)를 확인한다."""
        return is_chrome_running(self.profile_name)
