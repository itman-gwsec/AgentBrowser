#!/usr/bin/env python3
"""에이전트 브라우저(실제 headed Chrome)로 LLM 최신 연구를 단일 쿼리로 검색.

목적:
    기존 ``agent_search_qwen38.py`` 의 하드코딩 쿼리("qwen3.8에 대한 심층 분석")를
    범용화한다. 쿼리를 **인자(sys.argv[1])** 로 받아 실제 브라우저 검색을 1회 수행하고,
    추출된 링크(실제 URL + 제목)를 JSON 으로 저장한다.

    구글은 사용자 지시로 제외. DuckDuckGo / Bing 대상.

동작/안전:
    - ``build_launch_command`` 로 ``--enable-automation`` 없는 headed Chrome 기동.
    - ``CDPBridge`` 로 attach (navigator.webdriver=False 실측).
    - ``Humanizer`` + ``SearchDispatcher`` 로 인간유사 검색 → 링크 추출.
    - Bing 리다이렉트(``bing.com/ck/a?...&u=<base64>``)는 ``u=`` 파라미터를
      base64 디코딩해 실제 목적지 URL 로 복원.
    - 종료 시 Chrome 프로세스 정리.
    - print 금지 → logger.
    - 익스텐션(JS) 수정 금지 — core 모듈은 그대로 재사용.

CLI:
    python scripts/agent_search_llm_research.py "<QUERY>" [--out PATH]
    미지정 시 기본 출력: /tmp/llm_research_raw.json
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs

# scripts/ 실행 시에도 src 임포트 가능하도록 경로 세팅.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.cdp_bridge import BotDetectionError, CDPBridge  # noqa: E402
from core.humanizer import Humanizer  # noqa: E402
from core.launcher import CHROME_PATH, build_launch_command, is_chrome_running  # noqa: E402
from core.search import SearchConfig, SearchDispatcher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent_search_llm_research")

# 요약 문자열 파싱용 정규식: " - 제목 (URL)" 라인 → (제목, URL).
_LINK_PATTERN = re.compile(r"^\s*-\s+(.+?)\s+\((https?://[^)]+)\)$")

PORT = 9231
PROFILE = "agent_llm_research"
CDP_WAIT_MAX_S = 25.0

# 구글 제외 엔진 순서 (yahoo 는 SearchConfig 미지원이므로 DDG/Bing 만).
ENGINES: list[Literal["duckduckgo", "bing"]] = ["duckduckgo", "bing"]

# 풀/원본 저장 시 엔진 표기 매핑 (작업 명세: ddg/bing).
SOURCE_ENGINE_MAP: dict[str, str] = {"duckduckgo": "ddg", "bing": "bing"}

RESULT_PATH = Path("/tmp/llm_research_raw.json")


def _unwrap_url(url: str) -> str:
    """검색엔진 리다이렉트 래퍼 URL 을 실제 목적지로 풀어준다.

    - DuckDuckGo: ``https://duckduckgo.com/l/?uddg=<enc>`` → ``uddg`` 디코딩.
    - Bing: ``https://www.bing.com/ck/a?...&u=<base64>`` (또는 ``r=``) →
      ``u=``/``r=`` 파라미터를 base64url 디코딩해 실제 URL 로 복원.

    이미 실제 URL 이면 그대로 반환.

    Args:
        url: 추출된(가능성 있는 래퍼) URL.

    Returns:
        실제 목적지 URL 문자열.
    """
    # --- DuckDuckGo 래퍼 ---
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            qs = parse_qs(parsed.query)
            uddg = qs.get("uddg")
            if uddg:
                return uddg[0]
    except Exception:
        logger.debug("DDG URL 래퍼 해제 실패(무시) -> %s", url)

    # --- Bing ck/a 리다이렉트 (u= / r= base64) ---
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if "bing.com" in parsed.netloc and parsed.path.startswith("/ck/a"):
            qs = parse_qs(parsed.query)
            for key in ("u", "r"):
                vals = qs.get(key)
                if not vals:
                    continue
                raw = vals[0]
                decoded = ""
                # Bing 은 'a1' 2글자 접두사 뒤에 base64url(실제 URL) 을 둔다.
                # 1) 그대로 시도 → 2) 접두사 2글자 제거 후 재시도.
                for candidate in (raw, raw[2:] if len(raw) > 2 else ""):
                    if not candidate:
                        continue
                    padded = candidate + "=" * (-len(candidate) % 4)
                    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
                        try:
                            decoded = decoder(padded).decode("utf-8", "ignore")
                            if decoded.startswith("http"):
                                break
                        except Exception:
                            decoded = ""
                    if decoded.startswith("http"):
                        break
                if decoded.startswith("http"):
                    return decoded
    except Exception:
        logger.debug("Bing URL 래퍼 해제 실패(무시) -> %s", url)

    return url


def parse_links_from_summary(summary: str) -> list[dict]:
    """검색 요약 문자열에서 `` - 제목 (URL)`` 라인을 파싱해 링크 리스트로 반환.

    ``SearchEngine._summarize`` 가 만드는 형식:
        ``[search:{engine}] query='...' results=N``
        `` - {title} ({url})``

    Args:
        summary: 디스패처가 반환한 요약 문자열.

    Returns:
        ``[{\"title\": str, \"url\": str}, ...]`` (리다이렉트는 실제 URL 로 해제).
    """
    links: list[dict] = []
    for line in summary.splitlines():
        m = _LINK_PATTERN.match(line)
        if not m:
            continue
        title = m.group(1).strip()
        url = _unwrap_url(m.group(2).strip())
        if title and url.startswith("http"):
            links.append({"title": title, "url": url})
    return links


def launch_chrome() -> subprocess.Popen:
    """TCP 디버깅 포트로 headed Chrome 을 백그라운드 기동.

    M5 파이프(--remote-debugging-pipe) 트랜스포트는 이 macOS 호스트에서
    Chrome 이 fd 3/4 를 상속받음에도 불구하고 exit=13(\"Remote debugging
    pipe file descriptors are not open\") 으로 기동 실패한다(브라우저 프로세스
    재기동 시 파이프 fd 가 누락되는 macOS 전용 동작). 따라서 레거시 TCP 포트
    트랜스포트(--remote-debugging-port) 로 기동하고 CDPBridge(transport=\"port\")
    로 붙는다. localhost 루프백이라 방화벽 프롬프트는 유발하지 않는다.
    """
    extension_path = (PROJECT_ROOT / "src/extension").resolve()
    user_data_dir = PROJECT_ROOT / "profiles" / PROFILE
    user_data_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={user_data_dir}",
        f"--load-extension={extension_path}",
        "--no-first-run",
        "--no-default-browser-check",
        # ⚠ 금지: "--enable-automation" 은 절대 추가하지 않는다 (R2 봇회피).
        "about:blank",
    ]
    logger.info("Chrome 기동 명령: %s", " ".join(cmd))
    log_path = PROJECT_ROOT / "logs" / f"agent_llm_research_chrome_{PORT}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
    logger.info("Chrome PID=%s 기동 (port=%s)", proc.pid, PORT)
    return proc


def wait_for_cdp() -> None:
    """CDP HTTP 엔드포인트(127.0.0.1:PORT) 응답 대기 (최대 CDP_WAIT_MAX_S 폴링)."""
    import socket

    deadline = time.time() + CDP_WAIT_MAX_S
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1.0):
                logger.info("CDP 준비 완료 (port=%s)", PORT)
                return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"CDP_TIMEOUT_PORT_{PORT}")


def search_query(
    page: object,
    query: str,
    engines: list[Literal["duckduckgo", "bing"]],
    enable_google: bool = False,
) -> dict:
    """단일 쿼리를 지정 엔진들로 검색하고 링크를 모은다 (재사용 가능 함수).

    Args:
        page: CDPBridge 가 제공한 Playwright page 객체.
        query: 검색어.
        engines: 사용할 엔진 리스트 (기본 DDG/Bing, 구글 제외).

    Returns:
        ``{query, engines: {engine: {status, link_count}}, links}``.
        links 는 엔진별 링크를 (query/source_engine 메타 포함) 모은 리스트.
    """
    humanizer = Humanizer()
    per_engine: dict[str, dict] = {}
    combined: list[dict] = []
    for engine in engines:
        logger.info("=== [%s] 검색 시작: %r ===", engine, query)
        config = SearchConfig(engine=engine, enable_google=enable_google)
        dispatcher = SearchDispatcher(config, humanizer)
        try:
            out = dispatcher.run(page, query)
            if isinstance(out, str):
                links = parse_links_from_summary(out)
                logger.info("[%s] 검색 완료: 링크 %d건", engine, len(links))
                per_engine[engine] = {"status": "ok", "link_count": len(links)}
                for item in links:
                    combined.append(
                        {
                            "url": item["url"],
                            "title": item["title"],
                            "query": query,
                            "source_engine": SOURCE_ENGINE_MAP.get(engine, engine),
                        }
                    )
            else:
                # HITLRequest (캡차 등) — 인간 개입 필요.
                logger.warning("[%s] HITL 요청: %s", engine, getattr(out, "reason", "?"))
                per_engine[engine] = {
                    "status": "hitl",
                    "reason": getattr(out, "reason", "?"),
                }
        except BotDetectionError:
            logger.warning("[%s] 봇탐지 차단", engine)
            per_engine[engine] = {"status": "bot_detected"}
        except Exception as exc:
            logger.warning("[%s] 검색 실패: %s", engine, exc)
            per_engine[engine] = {"status": "error", "error": str(exc)[:200]}
    return {"query": query, "engines": per_engine, "links": combined}


def main() -> int:
    """단일 쿼리 LLM 연구 검색 메인.

    CLI:
        agent_search_llm_research.py "<QUERY>" [--out PATH]
    """
    parser = argparse.ArgumentParser(description="에이전트 브라우저 LLM 연구 검색(구글 제외)")
    parser.add_argument("query", help="검색어 (단일)")
    parser.add_argument("--out", default=str(RESULT_PATH), help="결과 JSON 경로")
    parser.add_argument(
        "--enable-google",
        action="store_true",
        default=False,
        help="google 엔진 사용 허용 (기본 비활성). SearchConfig.enable_google=True 매핑",
    )
    args = parser.parse_args()

    query = args.query.strip()
    out_path = Path(args.out)
    logger.info("=== 검색 시작 (엔진=%s, 쿼리=%r) ===", ENGINES, query)

    proc: subprocess.Popen | None = None
    bridge: CDPBridge | None = None
    exit_code = 0
    result: dict = {"query": query, "engines": {}, "links": []}

    try:
        proc = launch_chrome()
        wait_for_cdp()
        bridge = CDPBridge(port=PORT, transport="port")
        bridge.connect()
        page = bridge.page
        with suppress(Exception):
            page.set_default_timeout(15000)
        logger.info("CDP attach 완료 (url=%s)", page.url)

        result = search_query(page, query, ENGINES, enable_google=args.enable_google)

        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        logger.info(
            "결과 저장: %s (링크 %d건)", out_path, len(result.get("links", []))
        )
    except TimeoutError:
        logger.exception("CDP 대기 실패")
        exit_code = 2
    except Exception:
        logger.exception("예상치 못한 오류")
        exit_code = 2
    finally:
        if bridge is not None:
            with suppress(Exception):
                bridge._safe_disconnect()
        if proc is not None and proc.poll() is None:
            proc.terminate()
            with suppress(Exception):
                proc.wait(timeout=5)
            if proc.poll() is None:
                proc.kill()
        with suppress(Exception):
            subprocess.run(
                ["pkill", "-f", f"remote-debugging-port={PORT}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        logger.info("=== 정리 완료 (port=%s) ===", PORT)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
