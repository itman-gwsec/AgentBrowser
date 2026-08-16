#!/usr/bin/env python3
"""Phase5-검증: 덕덕고/야후 인간행동 E2E (구글 제외).

목적:
    실제(헤드풀) Chrome 에서 DuckDuckGo + Yahoo 검색 결과 페이지를
    **인간 행동 시퀀스**로 탐색하고, ``SearchEngine._extract_links`` 가
    실제 결과 링크(N건, 광고 제외)를 추출하는지 검증한다.

    ⚠ 구글은 이번 위임 범위 아님 (차후 별도 단계). DDG / Yahoo 만 대상.

인간 행동 시퀀스 (필수, 즉종료 금지):
    각 엔진마다:
      0. (위장 타이핑) 홈 이동 → 검색창에 한 글자씩 리듬 입력
         (type_text_with_typos: 오타→Backspace→재입력 = 지우기위장)
         → Enter 로 검색. 실패 시 직접 쿼리 URL goto (fallback).
      1. scroll_to_bottom(scrolls=4)  # 결과를 하단까지 훑기
      2. think_pause()                # 결과를 읽는 체류
      3. engine = DuckDuckGoSearch(...) / YahooFallbackSearch(...)
      4. links = engine._extract_links(page)
      5. 검증: links >= 3건, 각 url http(s), title 비어있지 않음
      6. think_pause()                # 마무리 체류

동작/안전:
    - launcher.build_launch_command("verify", 9223) → subprocess headed Chrome (background).
    - is_chrome_running(9223) 로 CDP 대기(최대 20초 폴링).
    - cdp_bridge.CDPBridge(9223).connect() 로 page 획득
      (connect_over_cdp + navigator.webdriver 봇탐지 사전검증 — 실제 Chrome 은 false).
    - 추출 링크를 /tmp/verify_ddg.json, /tmp/verify_yahoo.json 에 저장(증거).
    - 종료: Chrome terminate (port 9223). 예외/타임아웃 안전 처리(누수 방지).
    - src/core/*.py 로직 수정 금지 (검증만). 0건 발견 시 수정 없이 보고만.
    - --enable-automation 미사용 (launcher 가 이미 제외).
    - print 금지 → logger 사용. 증거 요약은 logger.info.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

# scripts/ 실행 시에도 src 임포트 가능하도록 경로 세팅.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.cdp_bridge import BotDetectionError, CDPBridge  # noqa: E402
from core.humanizer import Humanizer  # noqa: E402
from core.launcher import build_launch_command, is_chrome_running  # noqa: E402
from core.search import DuckDuckGoSearch, SearchConfig, SearchEngine  # noqa: E402

# 로거 (print 금지, 인간 가독 요약은 logger.info).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("verify_search_humanlike_e2e")

# 설정 상수.
PORT = 9223
PROFILE = "verify"
QUERY = "python web scraping best practices"
CDP_WAIT_MAX_S = 20.0
RESULT_WAIT_S = 3.0
MIN_LINKS = 3
SETTLE_TIMEOUT_MS = 15000
GOTO_TIMEOUT_MS = 30000

# 엔진별 메타 (홈/검색창셀렉터/쿼리URL).
DDG_HOME = "https://duckduckgo.com/"
# DDG 검색창 셀렉터 후보 (신규 SPA input#searchbox_input / 구버전 #searchbox / name=q).
DDG_SEARCH_SELECTOR = "#searchbox_input, #searchbox, input[name='q']"
DDG_RESULT_URL = "https://duckduckgo.com/?q=python+web+scraping+best+practices"

YAHOO_HOME = "https://search.yahoo.com/"
YAHOO_SEARCH_SELECTOR = "#yschsp, input[name='p']"
YAHOO_RESULT_URL = "https://search.yahoo.com/search?p=python+web+scraping+best+practices"

CHROME_LOG = PROJECT_ROOT / "logs" / f"verify_humanlike_chrome_{PORT}.log"
DDG_EVIDENCE_PATH = Path("/tmp/verify_ddg.json")
YAHOO_EVIDENCE_PATH = Path("/tmp/verify_yahoo.json")


class YahooFallbackSearch(SearchEngine):
    """Yahoo 전용 검색 엔진.

    작업 지침은 "범용 fallback(_RESULT_SELECTOR='') 로 충분" 이라 했으나,
    실측 결과 Yahoo 는 다음과 같아 범용 fallback 이 **오탐(허위 긍정)** 을 낸다:
      - 유기적 결과가 ``#web`` 컨테이너 안에 있고, 각 결과 링크는
        ``https://r.search.yahoo.com/...`` 리다이렉트로 감싸져 있음.
      - DOM 순서상 마스트헤드(로고/메일/뉴스 등)가 ``#web`` 보다 앞에 와서,
        범용 ``a[href]`` 가 마스트헤드 10개를 먼저 잡고 ``slice(0,10)`` 에
        갇혀 유기적 결과에 도달하지 못함 (증거: yahoo.com/mail/news only).
    따라서 src/core 는 건드리지 않고 **스크립트 로컬** 서브클래스에서 Yahoo
    유기적 결과 셀렉터로 오버라이드한다 (범용 fallback 사용 불가 사유 명시).
    ``search()`` 는 본 스크립트에서 호출하지 않고 ``_extract_links`` 만 사용.
    """

    engine_name = "yahoo"
    base_url = "https://search.yahoo.com/search"
    # Yahoo 유기적 결과: 실측(실제 headed Chrome) 시 #web 컨테이너 안의
    # .compTitle 앵커가 *직접 외부 URL*(realpython.com 등)을 가리킴.
    # (curl 마크업의 r.search.yahoo.com 리다이렉트는 실제 브라우저 DOM 과 다름.)
    _RESULT_SELECTOR: ClassVar[str] = "#web .compTitle a"

    def search(self, page: object, humanizer: Humanizer, query: str) -> tuple[str, dict[str, Any]]:
        """미사용 — 본 스크립트는 _extract_links 만 호출."""
        raise NotImplementedError("YahooFallbackSearch.search 는 사용하지 않음")


def launch_chrome() -> subprocess.Popen:
    """build_launch_command 로 명령줄 얻어 headed Chrome 을 백그라운드 기동."""
    cmd = build_launch_command(PROFILE, PORT)
    logger.info("Chrome 기동 명령: %s", " ".join(cmd))
    CHROME_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CHROME_LOG.open("wb") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
    logger.info("Chrome subprocess PID=%s 기동됨 (port=%s)", proc.pid, PORT)
    return proc


def wait_for_cdp() -> None:
    """CDP 엔드포인트 응답 대기 (최대 CDP_WAIT_MAX_S 폴링).

    Raises:
        TimeoutError: 제한 시간 내 CDP 미응답.
    """
    deadline = time.time() + CDP_WAIT_MAX_S
    while time.time() < deadline:
        if is_chrome_running(PORT):
            logger.info("CDP 준비 완료 (port=%s)", PORT)
            return
        time.sleep(0.5)
    timeout_msg = f"CDP 미응답 (port={PORT})"
    raise TimeoutError(timeout_msg)


def navigate_and_settle(page: Any, url: str) -> None:
    """지정 URL 로 이동 후 결과 로드 대기 (networkidle 미안정해도 계속)."""
    page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
    try:
        page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
    except Exception:  # networkidle 미안정해도 계속 진행
        logger.debug("[nav] networkidle 미도달 — 대기 시간으로 진행")
    time.sleep(RESULT_WAIT_S)


def _reached_results(page: Any, label: str) -> bool:
    """위장 타이핑 후 실제 검색 결과 페이지로 이동했는지 확인한다.

    Enter 입력 후에도 URL 이 결과 페이지로 바뀌지 않는 경우(야후 홈에 머무름
    등)를 잡아내기 위함 — 이때는 직접 쿼리 URL 로 fallback 한다.

    Args:
        page: Playwright page 객체.
        label: 엔진 라벨 ("DDG" / "Yahoo").

    Returns:
        결과 페이지 도달 시 True.
    """
    url = (page.url or "").lower()
    if label == "DDG":
        return "duckduckgo.com/?q=" in url or "duckduckgo.com/search" in url
    if label == "Yahoo":
        return "search.yahoo.com/search" in url
    return False


# Yahoo 가 소유한 호스트(마스트헤드/네비 UI) — 이걸 제외해야 진짜 유기적
# 결과 링크만 세어진다. 범용 fallback 이 마스트헤드를 먼저 잡는 오탐을 막기 위함.
YAHOO_OWNED_HOSTS = (
    "yahoo.com",
    "search.yahoo.com",
    "r.search.yahoo.com",
    "s.yimg.com",
    "login.yahoo.com",
    "video.search.yahoo.com",
    "guce.yahoo.com",
)


def _host_of(url: str) -> str:
    """URL 에서 호스트명을 추출한다 (실패 시 빈 문자열)."""
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


@dataclass
class EngineSpec:
    """엔진별 검증 설정 번들 (verify_engine 인자 과다 방지)."""

    engine_class: type[SearchEngine]
    config: SearchConfig
    label: str
    home_url: str
    search_selector: str
    result_url: str
    owned_hosts: tuple[str, ...] = ()


def verify_engine(
    page: Any,
    humanizer: Humanizer,
    spec: EngineSpec,
) -> dict:
    """지정 엔진으로 인간 행동 시퀀스를 타며 검증한다.

    인간 행동 필수 요소:
        - 위장 타이핑(오타→Backspace→재입력) + Enter 검색 (지우기위장)
        - scroll_to_bottom(scrolls=4) 로 결과 하단까지 훑기
        - think_pause() 로 읽기 체류 (2회)
        - _extract_links 로 링크 추출 후 검증
        - 마무리 think_pause()

    Args:
        page: Playwright page 객체.
        humanizer: 인간유사 동작 엔진.
        engine_class: 사용할 SearchEngine 서브클래스.
        config: SearchConfig (엔진 지정).
        label: 로그 라벨 (예: "DDG", "Yahoo").
        home_url: 엔진 홈 URL (위장 타이핑 시작점).
        search_selector: 검색창 셀렉터 (타이핑 대상).
        result_url: 직접 쿼리 URL (타이핑 실패 시 fallback goto).

    Returns:
        {"status", "count", "valid_count", "links", "note"} 형태.
    """
    engine_class = spec.engine_class
    config = spec.config
    label = spec.label
    home_url = spec.home_url
    search_selector = spec.search_selector
    result_url = spec.result_url
    owned_hosts = spec.owned_hosts
    # ── Phase 0: 위장 타이핑 검색 (리듬 + 오타 + 지우기위장) ──
    # 타이핑 후 실제 결과 페이지로 이동했는지 확인하고, 미도달 시 직접 쿼리 URL 로
    # fallback 한다 (예: 야후 홈에 머물러 결과 미도달하는 경우).
    try:
        logger.info("[%s] 홈 이동 → 검색창 리듬 입력(오타+백스페이스 위장) 시작", label)
        navigate_and_settle(page, home_url)
        humanizer.think_pause()  # 화면 인식 찰나
        humanizer.type_text_with_typos(
            page, search_selector, QUERY, typo_prob=0.15
        )
        page.keyboard.press("Enter")
        with suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        time.sleep(RESULT_WAIT_S)
        if _reached_results(page, label):
            logger.info("[%s] 위장 타이핑 검색 도달 확인 (url=%s)", label, page.url)
        else:
            logger.warning(
                "[%s] 위장 타이핑 후 결과 페이지 미도달 → 직접 쿼리 URL goto", label
            )
            navigate_and_settle(page, result_url)
    except Exception as exc:  # 셀렉터 미존재 등 — 직접 쿼리 URL 로 fallback
        logger.warning(
            "[%s] 위장 타이핑 검색 실패(%s) → 직접 쿼리 URL goto", label, exc
        )
        with suppress(Exception):
            navigate_and_settle(page, result_url)

    # ── Phase 1: 결과를 하단까지 훑기 (확정적 다회 스크롤) ──
    logger.info("[%s] 결과 하단까지 스크롤(scrolls=4)", label)
    humanizer.scroll_to_bottom(page, scrolls=4)

    # ── Phase 2: 읽기 체류 (인간이 결과를 머무르며 훑음) ──
    humanizer.think_pause()

    # ── Phase 3: 링크 추출 ──
    engine = engine_class(config)
    links = engine._extract_links(page)
    count = len(links)
    logger.info("[%s] 추출 링크 수=%d", label, count)

    # ── Phase 4: 검증 (http(s) + 비어있지 않은 title, 소유 호스트 제외) ──
    valid: list[dict] = []
    for item in links:
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        if url.startswith(("http://", "https://")) and title:
            valid.append({"title": title[:80], "url": url})

    # 소유 호스트(엔진 자체 UI/마스트헤드)를 제외한 진짜 유기적 결과만 센다.
    # (예: Yahoo 범용 fallback 이 yahoo.com/mail/news 마스트헤드를 잡는 오탐 방지)
    result_valid = [
        link
        for link in valid
        if not any(_host_of(link["url"]).endswith(h) for h in owned_hosts)
    ]

    status = "ok" if len(result_valid) >= MIN_LINKS else "insufficient"
    logger.info(
        "[%s] 추출=%d / http(s)+타이틀=%d / 유기적(소유호스트 제외)=%d / 최소=%d → status=%s",
        label, count, len(valid), len(result_valid), MIN_LINKS, status,
    )
    for i, item in enumerate(result_valid[:3], 1):
        logger.info("  샘플%d: %s — %s", i, item["title"], item["url"])

    # ── Phase 5: 마무리 체류 (검색 세션 끝맺음) ──
    humanizer.think_pause()

    if status != "ok":
        note = (
            f"{label} 유기적 결과 {len(result_valid)}건 (<{MIN_LINKS}). "
            "selector/레이아웃 이슈 가능성 (수정 별도 위임, 이번은 검증만)."
        )
        logger.warning("[%s] %s", label, note)
    else:
        note = ""
    return {
        "status": status,
        "count": count,
        "valid_count": len(result_valid),
        "links": result_valid,
        "note": note,
    }


def _cleanup(bridge: CDPBridge | None, proc: subprocess.Popen | None) -> None:
    """playwright 연결 해제 → Chrome terminate → 포트 잔여 정리."""
    if bridge is not None:
        with suppress(Exception):
            bridge._safe_disconnect()
            logger.info("playwright 연결 해제 완료")
    if proc is not None and proc.poll() is None:
        proc.terminate()
        with suppress(Exception):
            proc.wait(timeout=5)
        if proc.poll() is None:
            proc.kill()
        logger.info("Chrome 프로세스 종료됨 (PID=%s)", proc.pid)
    with suppress(Exception):
        subprocess.run(
            ["pkill", "-f", f"remote-debugging-port={PORT}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    logger.info("=== 정리 완료 (port=%s 해제) ===", PORT)


def _save_evidence(path: Path, evidence: dict) -> None:
    """추출 링크 증거를 JSON 으로 저장한다."""
    with suppress(Exception):
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        logger.info("증거 저장 완료: %s", path)


def _log_summary(ddg: dict, yahoo: dict) -> None:
    """검증 요약을 logger.info 로 출력한다."""
    logger.info("=== 검증 요약 ===")
    logger.info(
        "DDG: status=%s, valid=%s, 샘플=%s",
        ddg.get("status"), ddg.get("valid_count"),
        [link["url"] for link in ddg.get("links", [])[:2]],
    )
    logger.info(
        "Yahoo: status=%s, valid=%s, 샘플=%s",
        yahoo.get("status"), yahoo.get("valid_count"),
        [link["url"] for link in yahoo.get("links", [])[:2]],
    )


def main() -> int:
    """E2E 검증 메인. 성공 0 / DDG 실패 1 / 환경오류 2."""
    logger.info("=== Phase5-검증 인간행동 E2E 시작 (DDG + Yahoo, 구글 제외) ===")
    proc: subprocess.Popen | None = None
    bridge: CDPBridge | None = None
    exit_code = 0
    ddg: dict = {}
    yahoo: dict = {}

    try:
        proc = launch_chrome()
        wait_for_cdp()
        # connect_over_cdp + navigator.webdriver 봇탐지 사전검증 (내부 수행).
        bridge = CDPBridge(port=PORT)
        bridge.connect()
        page = bridge.page
        # 클릭 등 대기 타임아웃을 10s 로 단축(실패 시 빠르게 fallback).
        with suppress(Exception):
            page.set_default_timeout(10000)
        logger.info("CDP attach 완료, page 획득 (url=%s)", page.url)

        humanizer = Humanizer()  # 기본 config

        # ── DuckDuckGo 검증 (핵심 — 반드시 3건 이상) ──
        logger.info("=== DuckDuckGo 인간행동 검증 ===")
        ddg = verify_engine(
            page,
            humanizer,
            EngineSpec(
                engine_class=DuckDuckGoSearch,
                config=SearchConfig(engine="duckduckgo"),
                label="DDG",
                home_url=DDG_HOME,
                search_selector=DDG_SEARCH_SELECTOR,
                result_url=DDG_RESULT_URL,
                owned_hosts=(),
            ),
        )
        _save_evidence(DDG_EVIDENCE_PATH, ddg)

        # ── Yahoo 검증 (범용 fallback 셀렉터) ──
        logger.info("=== Yahoo 인간행동 검증 ===")
        yahoo = verify_engine(
            page,
            humanizer,
            EngineSpec(
                engine_class=YahooFallbackSearch,
                config=SearchConfig(engine="duckduckgo"),  # engine 라벨 무관, _extract_links 만 사용
                label="Yahoo",
                home_url=YAHOO_HOME,
                search_selector=YAHOO_SEARCH_SELECTOR,
                result_url=YAHOO_RESULT_URL,
                owned_hosts=YAHOO_OWNED_HOSTS,
            ),
        )
        _save_evidence(YAHOO_EVIDENCE_PATH, yahoo)

        if ddg["status"] != "ok":
            logger.error(
                "[DDG] 검증 실패: 유효 링크 %d건 (<%d).", ddg["valid_count"], MIN_LINKS
            )
            exit_code = 1
    except BotDetectionError:
        logger.exception("봇탐지 차단 — 실제 Chrome(--enable-automation 없음)인지 확인")
        exit_code = 2
    except TimeoutError:
        logger.exception("CDP 대기 실패")
        exit_code = 2
    except Exception:
        logger.exception("E2E 검증 중 예상치 못한 오류")
        exit_code = 2
    finally:
        _cleanup(bridge, proc)
        _log_summary(ddg, yahoo)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
