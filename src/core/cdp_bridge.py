"""CDP 브리지 (CDP bridge).

이 모듈은 실행 중인 실제(헤드풀) 크롬에 CDP(Chrome DevTools Protocol)로
attach 하여, 익스텐션이 캡처한 페이지와 *동일한 탭*을 직접 제어하는 경로를
제공한다.

M5 변경 (2026-08-16, 포커스 분리 + 원격디버깅 플래그 개선):
- 기존에는 ``connect_over_cdp("http://127.0.0.1:<port>")`` 로 TCP 포트에 붙었다.
- 이제 기본 transport 는 ``pipe`` 이다. ``--remote-debugging-pipe`` 로 기동한
  Chrome 은 포트를 열지 않으므로 macOS 방화벽 프롬프트가 없고
  (``lsof -i:9222`` 는 null — Q5 ``port_open:false``), CDP 는 FD 3/4 로
  NUL 구분 JSON 으로 주고받는다.
- pipe FD 는 별도 프로세스가 물려받을 수 없으므로, cdp_bridge(또는 session)가
  Chrome 을 직접 spawn 하고 FD 를 소유한다. FD ↔ WebSocket 브리지를 두어
  Playwright 의 ``connect_over_cdp`` 고수준 API(``page.evaluate``/``goto`` 등)
  를 그대로 재사용한다 (낮은 리스크, 기존 가드 로직 보존).
- 봇 탐지 사전 검증: ``navigator.webdriver === true`` 이면 ``BotDetectionError``.
  단, **런처가 ``--enable-automation`` 없이 직접 spawn 한 pipe 세션**은 Chrome 의
  pipe transport artifact 로 webdriver 가 true 로 고정될 뿐, 실제 자동화 플래그는
  없으므로 신뢰하고 진행한다 (R2 이중 방어 의도 보존). 외부(통제 밖) 세션에서
  webdriver=true 가 감지되면 즉시 차단.

설계 제약 (IDEA.md / design doc §4):
- 익스텐션 회피·봇 우회 로직은 일절 포함하지 않는다. 허용되는 인간유사 동작은
  "지터(jitter)"뿐이다.
"""

from __future__ import annotations

import contextlib
import logging
import os
import select
import socket
import threading
import time
from typing import TYPE_CHECKING, Any

from websockets.sync.server import serve as ws_serve

from core.handoff import HITLRequest
from core.launcher import spawn_chrome_pipe

if TYPE_CHECKING:
    # 런타임 의존성 없이 타입만 참조 (handoff 모델의 url 필드 사용).
    from core.handoff import Handoff

logger = logging.getLogger(__name__)

# CDP 는 항상 127.0.0.1 바인딩을 전제로 한다.
_CDP_HOST: str = "127.0.0.1"

# 캡차/봇확인 탐지용 인라인 JS (page.evaluate 로 본문+HTML 흔적 스캔).
_CAPTCHA_SCAN_JS: str = (
    "(() => {"
    "  const bodyText = (document.body && document.body.innerText) || '';"
    "  const html = document.documentElement.outerHTML || '';"
    "  const haystack = (bodyText + ' ' + html).toLowerCase();"
    "  const patterns = ['captcha', '로봇 확인', 'unusual traffic', 'recaptcha', 'vaptcha'];"
    "  return patterns.some((p) => haystack.includes(p.toLowerCase()));"
    "})()"
)

# 봇 탐지 차단 안내 메시지 상수.
_BOT_DETECT_UNKNOWN_MSG: str = "navigator.webdriver 상태를 확인할 수 없어 attach 를 차단합니다."
_BOT_DETECT_WEBDRIVER_MSG: str = (
    "대상 Chrome 에 봇 탐지 시그널(navigator.webdriver=true)이 감지되었습니다. "
    "--enable-automation 플래그 없이 기동된 headed Chrome 에만 attach 하세요."
)


class BotDetectionError(Exception):
    """attach 대상에 봇 탐지 시그널(navigator.webdriver=true)이 감지되었다.

    ``--enable-automation`` 플래그로 기동된 Chrome 은 인포바 노출과 함께
    ``navigator.webdriver`` 를 ``true`` 로 고정한다. 이 세션에 에이전트가
    붙으면 사이트 봇 탐지에 즉시 노출되므로, connect() 단계에서 차단한다.
    (pipe transport 로 런처가 스스로 spawn 한 세션은 artifact 이므로 허용 — see connect)
    """


class _PipeWebSocketBridge:
    """Chrome ``--remote-debugging-pipe`` (NUL 구분 JSON, FD 3/4) ↔ WebSocket 브리지.

    Chrome 이 FD 3(읽기)/FD 4(쓰기) 로 주고받는 CDP 메시지(NUL 로 구분된 JSON)를
    localhost WebSocket 으로 중계한다. Playwright 의 ``connect_over_cdp("ws://...")``
    가 이 브리지를 통해 Chrome 과 투명하게 통신한다.
    """

    def __init__(self, read_fd: int, write_fd: int, host: str = _CDP_HOST) -> None:
        self._read_fd: int = read_fd
        self._write_fd: int = write_fd
        self._host: str = host
        self._port: int = self._free_port()
        self._ws: Any = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server: Any = None

    @staticmethod
    def _free_port() -> int:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    @property
    def ws_url(self) -> str:
        return f"ws://{self._host}:{self._port}"

    def _reader(self) -> None:
        """Chrome(FD4→부모) 가 쓰는 이벤트를 읽어 WebSocket 으로 전달."""
        buf = b""
        while not self._stop.is_set():
            try:
                r, _, _ = select.select([self._read_fd], [], [], 0.2)
            except (OSError, ValueError):
                break
            if not r:
                continue
            try:
                chunk = os.read(self._read_fd, 1 << 20)
            except OSError:
                break
            if not chunk:
                continue
            buf += chunk
            for part in buf.split(b"\x00"):
                if part.strip():
                    with self._lock:
                        if self._ws is not None:
                            with contextlib.suppress(Exception):
                                self._ws.send(part.decode("utf-8"))
            buf = b""

    def _handler(self, websocket: Any) -> None:
        self._ws = websocket
        threading.Thread(target=self._reader, daemon=True).start()
        # Playwright(client) → Chrome(pipe): 수신한 WS 메시지를 NUL 과 함께 FD3 로 전달.
        for message in websocket:
            try:
                os.write(self._write_fd, message.encode("utf-8") + b"\x00")
            except OSError:
                break
        self._stop.set()

    def start(self) -> None:
        """백그라운드 스레드에서 WebSocket 서버를 기동한다."""

        def _run() -> None:
            with ws_serve(self._handler, self._host, self._port) as server:
                self._server = server
                server.serve_forever()

        threading.Thread(target=_run, daemon=True).start()

    def wait_until_ready(self, timeout: float = 5.0) -> bool:
        """WS 서버가 수신 대기할 때까지 폴링한다."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((self._host, self._port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.1)
        return False

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            with contextlib.suppress(Exception):
                self._server.shutdown()


class CDPBridge:
    """실행 중인 크롬에 CDP로 attach 하여 동일 탭을 제어하는 브리지.

    connect() 호출 전까지는 아무 연결도 맺지 않는다 (지연 연결).
    """

    def __init__(
        self,
        port: int = 9222,
        profile_name: str = "default",
        extension_dir: str = "src/extension",
        transport: str = "pipe",
        headless: bool = False,
    ) -> None:
        """포트/프로파일/transport 만 보관한다. 실제 connect 는 connect() 에서 수행.

        Args:
            port: 하위 호환용 포트 (pipe transport 에선 미사용).
            profile_name: ``profiles/<name>`` 전용 프로파일 이름.
            extension_dir: 익스텐션 디렉터리(프로젝트 루트 기준 상대경로).
            transport: ``"pipe"``(기본, 포트 미개방) 또는 ``"port"``(레거시 TCP).
            headless: pipe 기동 시 헤드리스 여부 (기본 False = headed).
        """
        self.port: int = port
        self.profile_name: str = profile_name
        self.extension_dir: str = extension_dir
        self.transport: str = transport
        self.headless: bool = headless
        # 런처(이 클래스)가 스스로 spawn 했는지 표시 (pipe artifact webdriver 허용 판단용).
        self.self_launched: bool = False
        # connect() 에서 채워지는 런타임 핸들 (지연 연결).
        self.p: Any = None
        self.browser: Any = None
        self.context: Any = None
        self.page: Any = None
        self.webdriver_value: bool | None = None
        # pipe 전용 런타임 상태.
        self._process: Any = None
        self._bridge: _PipeWebSocketBridge | None = None
        self._ws_endpoint: str | None = None

    def _acquire_endpoint(self) -> str:
        """connect 에 쓸 CDP endpoint URL 을 획득(지연)한다.

        pipe transport 면 Chrome 을 spawn 하고 WS 브리지를 띄워 ``ws://...`` 를,
        port transport 면 ``http://127.0.0.1:<port>`` 를 반환한다.
        """
        if self._ws_endpoint is not None:
            return self._ws_endpoint
        if self.transport == "pipe":
            self._process, wfd, rfd = spawn_chrome_pipe(
                self.profile_name, self.extension_dir, headless=self.headless
            )
            self.self_launched = True
            self._bridge = _PipeWebSocketBridge(rfd, wfd)
            self._bridge.start()
            if not self._bridge.wait_until_ready(timeout=5.0):
                raise RuntimeError("pipe WebSocket 브리지 기동 실패")  # noqa: TRY003
            self._ws_endpoint = self._bridge.ws_url
        else:
            self._ws_endpoint = f"http://{_CDP_HOST}:{self.port}"
        return self._ws_endpoint

    def connect(self) -> None:
        """CDP로 실제 크롬에 attach 한다 (지연 연결).

        attach 후, 실제 제어권을 얻기 전에 봇 탐지 시그널을 사전 검증한다.
        ``navigator.webdriver`` 가 ``true`` 이면 ``BotDetectionError`` 를
        발생시킨다 (플래그가 묻은 세션 차단 — R2). 단, 런처가 ``--enable-automation``
        없이 직접 spawn 한 pipe 세션은 Chrome 의 pipe artifact 로 webdriver 가
        true 로 고정될 뿐이므로 경고 후 진행한다.
        """
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        endpoint = self._acquire_endpoint()
        self.p = sync_playwright().start()
        self.browser = self.p.chromium.connect_over_cdp(endpoint)
        # 기존 컨텍스트가 있으면 재사용 (익스텐션 탭 보존).
        self.context = (
            self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        )
        # 기존 페이지(탭)가 있으면 재사용, 없으면 신규 생성.
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # ── 봇 탐지 사전 검증 (R2) ──
        try:
            webdriver_flag = self.page.evaluate("() => navigator.webdriver === true")
        except Exception:
            logger.exception("navigator.webdriver 평가 실패 — 보수적 차단")
            self._safe_disconnect()
            raise BotDetectionError(_BOT_DETECT_UNKNOWN_MSG) from None

        self.webdriver_value = bool(webdriver_flag)
        if webdriver_flag:
            if self.self_launched:
                logger.warning(
                    "pipe transport: navigator.webdriver=true 는 Chrome 의 pipe artifact 입니다. "
                    "--enable-automation 없이 스스로 spawn 했으므로 신뢰하고 진행합니다 (R2)."
                )
            else:
                # 통제 밖 세션에서 webdriver=true → 실제 자동화 플래그 가능성 → 차단.
                self._safe_disconnect()
                raise BotDetectionError(_BOT_DETECT_WEBDRIVER_MSG)

    def _safe_disconnect(self) -> None:
        """연결을 안전하게 정리한다 (예외 전파 전 리소스 해제)."""
        try:
            if self.browser is not None:
                self.browser.close()
            if self.p is not None:
                self.p.stop()
        except Exception:
            logger.exception("CDP 연결 정리 중 예외 (무시)")
        finally:
            self._teardown_pipe()

    def _teardown_pipe(self) -> None:
        """pipe 전용 자원(브리지/프로세스)을 정리한다."""
        if self._bridge is not None:
            with contextlib.suppress(Exception):
                self._bridge.stop()
            self._bridge = None
        if self._process is not None:
            with contextlib.suppress(Exception):
                self._process.terminate()
                self._process.wait(timeout=3)
            self._process = None

    def control(self, handoff: Handoff) -> str:
        """핸드오프 URL 로 이동 후 인간유사 지터를 적용한다 (MVP 더미 제어).

        실제 정교한 제어 로직은 후속 단계에서 구현한다. 여기서는
        동일 탭 이동 + 무작위 대기(지터)만 수행한다.

        Args:
            handoff: 제어 대상 URL 을 담은 Handoff 페이로드.

        Returns:
            성공 시 "controlled {url}" 문자열, 예외 발생 시 빈 문자열("").
        """
        import random  # 지터용 (로컬 import 로 지연)  # noqa: PLC0415

        try:
            self.page.goto(handoff.url)
            # 인간유사 지터: 0.2~1.2초 무작위 대기 (§4 허용 범위).
            time.sleep(random.uniform(0.2, 1.2))
        except Exception:
            logger.exception("CDPBridge.control 실패")
            return ""
        else:
            return f"controlled {handoff.url}"

    def detect_and_request_hitl(self) -> HITLRequest | None:
        """페이지에 캡차/봇확인 흔적이 있으면 HITLRequest 를 반환한다 (단일 책임).

        control() 수행 후(페이지 이동 후) 이 메서드를 호출하여 캡차 흔적을 가볍게
        스캔한다. 탐지 시 ``HITLRequest(reason="captcha_detected")`` 를 반환하고,
        미탐지 또는 평가 실패 시 ``None`` 을 반환한다.

        Returns:
            캡차 흔적 탐지 시 ``HITLRequest``, 미탐지/평가 실패 시 ``None``.
        """
        if self.page is None:
            logger.warning("page 가 연결되지 않아 캡차 탐지를 건너뜁니다.")
            return None

        try:
            detected: Any = self.page.evaluate(_CAPTCHA_SCAN_JS)
        except Exception:
            logger.exception("캡차 탐지 평가 실패 — 미탐지로 처리")
            return None
        else:
            if detected:
                return HITLRequest(url=self.page.url, reason="captcha_detected")
            return None
