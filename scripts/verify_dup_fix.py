"""중복 타이핑 버그픽스 실제 브라우저 검증 (Bing·Google·DDG).

Humanizer.type_text_with_typos 의 오타 보정 중복 버그가 수정되었는지
실제(헤드풀) Chrome 로 검증한다. typo_prob=0.15 로 "test query" 를 입력한 뒤
각 엔진 검색창의 실제 input.value 가 원본과 일치하는지(중복 없음) 확인한다.

실행: PYTHONPATH=src .venv/bin/python scripts/verify_dup_fix.py
전제: port 9227 에 --enable-automation 없이 기동된 headed Chrome 이 떠 있어야 함
      (launcher.build_launch_command("verify", 9227) 로 기동).
결과: /tmp/verify_dup_fix_result.json (엔진별 입력값 + 중복여부)

코어 코드/익스텐션 JS 수정 금지 규칙 준수 — 본 스크립트는 관찰만 수행.
구글 검색은 이번 검증에서만 허용(사용자 지시).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from core.cdp_bridge import CDPBridge
from core.humanizer import Humanizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    filename="/tmp/verify_dup_fix.log",
)
logger = logging.getLogger("verify_dup_fix")

PORT = 9227
QUERY = "test query"
OUT_PATH = Path("/tmp/verify_dup_fix_result.json")

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
        txt = page.evaluate("() => (document.body && document.body.innerText) || ''") or ""
        url = page.url or ""
        hay = (txt + " " + url).lower()
        markers = ["captcha", "로봇 확인", "unusual traffic", "recaptcha", "vaptcha"]
        return ";".join(m for m in markers if m in hay)
    except Exception:
        return ""


def observe_engine(  # noqa: PLR0913, PLR0917
    page, humanizer: Humanizer, name: str, url: str, selector: str, typo_prob: float
) -> dict:
    logger.info("[%s] navigate -> %s (typo_prob=%.2f)", name, url, typo_prob)
    page.goto(url, timeout=30000)
    time.sleep(1.2)  # 필드 프리필 대기
    prefill = _read_value(page, selector)
    # 수정된 Humanizer 로 "test query" 입력 (오타 시뮬 포함).
    humanizer.type_text_with_typos(
        page, selector, QUERY, typo_prob=typo_prob, typing_x=1.0, pause_x=1.0
    )
    typed = _read_value(page, selector)
    captcha = _captcha_hint(page)
    return {
        "selector": selector,
        "prefill_value": prefill,
        "input_value_after_type": typed,
        "expected_value": QUERY,
        "dup_detected": typed != QUERY,
        "captcha_markers": captcha,
        "blocked": bool(captcha),
    }


def main() -> None:
    bridge = CDPBridge(PORT)
    bridge.connect()
    logger.info("CDP 연결 성공 (navigator.webdriver 검증 통과 가정)")
    humanizer = Humanizer()

    results: dict[str, dict] = {}
    for name, (url, selector) in ENGINES.items():
        try:
            page = bridge.context.new_page()
            # 깨끗한 필드 클리어 동작 격리 관찰 (오타 배제).
            clean = observe_engine(page, humanizer, name, url, selector, typo_prob=0.0)
            # 실제 search() 와 동일하게 typo_prob=0.15 로 관찰 (오타 보정 중복 검출).
            real = observe_engine(page, humanizer, name, url, selector, typo_prob=0.15)
            results[name] = {
                "clean_typo0": clean,
                "real_typo015": real,
            }
            page.close()
            logger.info(
                "[%s] real typed=%r dup=%s",
                name,
                real["input_value_after_type"],
                real["dup_detected"],
            )
        except Exception:
            logger.exception("[%s] 관찰 실패", name)
            results[name] = {"error": "observe_failed"}

    payload = {
        "bing": results.get("bing", {}),
        "google": results.get("google", {}),
        "ddg": results.get("ddg", {}),
        "_meta": {
            "method": (
                "CDPBridge(9227).connect() → Humanizer().type_text_with_typos("
                "'test query', typo_prob=0.15) → page.input_value(셀렉터) 확인."
            ),
            "humanizer_fix": (
                "type_text_with_typos 오타 보정 경로에서 원글자 재타입(type(char)) "
                "제거 → 글자 중복 방지."
            ),
            "query": QUERY,
            "typo_prob": 0.15,
            "all_clean": all(
                not results.get(eng, {}).get("real_typo015", {}).get("dup_detected", True)
                for eng in ("bing", "google", "ddg")
            ),
        },
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("결과 저장: %s", OUT_PATH)


if __name__ == "__main__":
    main()
