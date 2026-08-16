"""검색 입력 중복 타이핑 관찰 테스트 (단일 에이전트, 관찰 전용).

코어 코드(cdp_bridge / humanizer)를 직접 호출하여 Bing·Google·DDG 검색창에
"test query" 를 입력한 뒤 실제 input.value 를 확인한다. 중복 타이핑 여부를
판단한다. 코어 코드는 수정하지 않는다 (관찰만).

실행: PYTHONPATH=src .venv/bin/python scripts/test_search_dup_observe.py
전제: port 9227 에 headed Chrome 이 이미 기동되어 있어야 함
      (launcher.build_launch_command("verify", 9227) 로 생성된 명령으로 기동).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from core.cdp_bridge import CDPBridge
from core.humanizer import Humanizer

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    filename="/tmp/search_dup_test.log",
)
logger = logging.getLogger("search_dup_observe")

PORT = 9227
QUERY = "test query"
OUT_PATH = Path("/tmp/search_dup_test.json")

# 엔진별 (goto URL, 검색창 셀렉터)
ENGINES = {
    "bing": ("https://www.bing.com/search?q=test", "#sb_form_q"),
    "google": ("https://www.google.com/search?q=test", "textarea[name=q], input[name=q]"),
    "ddg": ("https://duckduckgo.com/?q=test", "#search_form_input"),
}


def _read_value(page, selector: str) -> str:
    """검색창의 실제 input.value 를 읽는다 (예외 시 빈 문자열)."""
    try:
        return str(page.input_value(selector))
    except Exception:
        logger.exception("input_value 실패 (selector=%s)", selector)
        return ""


def _captcha_hint(page) -> str:
    """캡차/봇차단 흔적을 본문+URL 에서 스캔한다."""
    try:
        txt = (page.evaluate("() => (document.body && document.body.innerText) || ''") or "")
        url = page.url or ""
        hay = (txt + " " + url).lower()
        markers = ["captcha", "로봇 확인", "unusual traffic", "recaptcha", "vaptcha", "unusual activity"]
        hits = [m for m in markers if m in hay]
        return ";".join(hits)
    except Exception:
        return ""


def observe_engine(page, humanizer: Humanizer, name: str, url: str, selector: str, typo_prob: float) -> dict:
    logger.info("[%s] navigate -> %s (typo_prob=%.2f)", name, url, typo_prob)
    page.goto(url, timeout=30000)
    time.sleep(1.2)  # 필드 프리필 대기
    prefill = _read_value(page, selector)
    # Humanizer 가 제공하는 검색입력 헬퍼 사용 (오타 시뮬 포함).
    humanizer.type_text_with_typos(
        page, selector, QUERY, typo_prob=typo_prob, typing_x=1.0, pause_x=1.0
    )
    typed = _read_value(page, selector)
    captcha = _captcha_hint(page)
    dup = typed != QUERY
    rec = {
        "prefill_value": prefill,
        "input_value_after_type": typed,
        "expected_value": QUERY,
        "dup_detected": dup,
        "captcha_markers": captcha,
        "blocked": bool(captcha),
        "note": (
            "필드 초기값 보존(클리어 실패)" if prefill and not typed.startswith(prefill.replace(QUERY, ""))
            else ""
        ),
    }
    logger.info("[%s] typed=%r dup=%s captcha=%r", name, typed, dup, captcha)
    return rec


def main() -> None:
    bridge = CDPBridge(PORT)
    bridge.connect()
    logger.info("CDP 연결 성공 (navigator.webdriver 검증 통과 가정)")
    humanizer = Humanizer()

    results: dict[str, dict] = {}
    for name, (url, selector) in ENGINES.items():
        try:
            page = bridge.context.new_page()
            # 깨끗한 필드 클리어 동작만 격리 관찰 (오타 시뮬 배제).
            clean = observe_engine(page, humanizer, name, url, selector, typo_prob=0.0)
            # 실제 search() 와 동일하게 typo_prob=0.15 로도 관찰 (오타 보정 중복 검출).
            real = observe_engine(page, humanizer, name, url, selector, typo_prob=0.15)
            results[name] = {
                "selector": selector,
                "clean_typo0": clean,
                "real_typo015": real,
            }
            page.close()
        except Exception:
            logger.exception("[%s] 관찰 실패", name)
            results[name] = {"error": "observe_failed"}

    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("결과 저장: %s", OUT_PATH)


if __name__ == "__main__":
    main()
