#!/usr/bin/env python3
"""에이전트가 에이전트 브라우저(실제 Chrome)로 직접 검색 수행.

목적:
    검증 스크립트(verify_*.py)가 아니라, **에이전트가 실제로 브라우저를
    제어하여 검색을 수행**하는 경로(Runner → SearchDispatcher → Humanizer)를
    타고 "qwen3.8에 대한 심층 분석"을 구글 제외 엔진에서 실행한다.

    구글은 사용자 지시로 제외. DuckDuckGo / Bing / Yahoo(선택) 대상.

인간 행동 시퀀스 (Phase5 보강 적용):
    - 위장 타이핑(type_text_with_typos: 오타→Backspace→재입력)
    - 결과 하단까지 스크롤(scroll_to_bottom)
    - 읽기 체류(think_pause)
    - hover 클릭 / 새 탭 열기
    - 마무리 체류

동작/안전:
    - launcher.build_launch_command 로 --enable-automation 없는 headed Chrome 기동.
    - CDPBridge 로 attach (navigator.webdriver=False 실측).
    - 종료 시 Chrome 프로세스 정리.
    - print 금지 → logger.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

# scripts/ 실행 시에도 src 임포트 가능하도록 경로 세팅.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.cdp_bridge import BotDetectionError, CDPBridge  # noqa: E402
from core.humanizer import Humanizer  # noqa: E402
from core.launcher import build_launch_command, is_chrome_running  # noqa: E402
from core.search import SearchConfig, SearchDispatcher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent_search_qwen38")

PORT = 9225
PROFILE = "agent_qwen38"
QUERY = "qwen3.8에 대한 심층 분석"
CDP_WAIT_MAX_S = 20.0
RESULT_PATH = Path("/tmp/qwen38_analysis.json")

# 구글 제외 엔진 순서 (yahoo 는 SearchConfig 미지원이므로 DDG/Bing 만).
ENGINES = ["duckduckgo", "bing"]


def launch_chrome() -> subprocess.Popen:
    """build_launch_command 로 명령줄 얻어 headed Chrome 을 백그라운드 기동."""
    cmd = build_launch_command(PROFILE, PORT)
    logger.info("Chrome 기동 명령: %s", " ".join(cmd))
    log_path = PROJECT_ROOT / "logs" / f"agent_qwen38_chrome_{PORT}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
    logger.info("Chrome PID=%s 기동 (port=%s)", proc.pid, PORT)
    return proc


def wait_for_cdp() -> None:
    """CDP 엔드포인트 응답 대기 (최대 CDP_WAIT_MAX_S 폴링)."""
    deadline = time.time() + CDP_WAIT_MAX_S
    while time.time() < deadline:
        if is_chrome_running(PORT):
            logger.info("CDP 준비 완료 (port=%s)", PORT)
            return
        time.sleep(0.5)
    raise TimeoutError(f"CDP 미응답 (port={PORT})")


def main() -> int:
    """에이전트 검색 실행 메인."""
    logger.info("=== 에이전트 브라우저 직접 검색 시작 (구글 제외: %s) ===", ENGINES)
    proc: subprocess.Popen | None = None
    bridge: CDPBridge | None = None
    exit_code = 0
    results: dict[str, object] = {}

    try:
        proc = launch_chrome()
        wait_for_cdp()
        bridge = CDPBridge(port=PORT)
        bridge.connect()
        page = bridge.page
        with suppress(Exception):
            page.set_default_timeout(10000)
        logger.info("CDP attach 완료 (url=%s)", page.url)

        humanizer = Humanizer()
        # 엔진별로 순차 검색 (세션 간격 적용 — 서버측 패턴 완화).
        for engine in ENGINES:
            logger.info("=== [%s] 검색 시작: %r ===", engine, QUERY)
            config = SearchConfig(engine=engine)
            dispatcher = SearchDispatcher(config, humanizer, cdp_bridge=bridge)
            try:
                out = dispatcher.run(page, QUERY)
                if isinstance(out, str):
                    # 요약 문자열 — 링크 수 추출.
                    n_links = out.count(" - ") if " - " in out else 0
                    logger.info("[%s] 검색 완료: 링크 %d건", engine, n_links)
                    results[engine] = {
                        "status": "ok",
                        "summary": out[:2000],
                        "link_count": n_links,
                    }
                else:
                    # HITLRequest (캡차 등) — 인간 개입 필요.
                    logger.warning("[%s] HITL 요청: %s", engine, getattr(out, "reason", "?"))
                    results[engine] = {"status": "hitl", "reason": getattr(out, "reason", "?")}
            except BotDetectionError:
                logger.warning("[%s] 봇탐지 차단", engine)
                results[engine] = {"status": "bot_detected"}
            except Exception as exc:
                logger.warning("[%s] 검색 실패: %s", engine, exc)
                results[engine] = {"status": "error", "error": str(exc)[:200]}
            # 세션 간격 (다음 엔진 전 무작위 대기).
            if engine != ENGINES[-1]:
                humanizer.session_gap()

        # 전체 결과 저장.
        RESULT_PATH.write_text(
            json.dumps(
                {"query": QUERY, "engines": ENGINES, "results": results},
                ensure_ascii=False,
                indent=2,
            )
        )
        logger.info("결과 저장: %s", RESULT_PATH)
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
