#!/usr/bin/env python3
"""실제 브라우저(Bing) 중복 입력 재검증 — 버그 A 수정 확인.

위임 허용 대안(별도 검증 스크립트)으로, 제품 코드(Humanizer)를 실제 Chromium
으로 Bing(#sb_form_q) 에 적용해 중복 입력이 없는지 확인한다.

시나리오:
    1. Bing 접속 후 검색창에 잔존 텍스트("OLDTEXT")를 타이핑(이전 세션 잔존 가정).
    2. 실제 Humanizer.type_text_with_typos(..., typo_prob=0) 로 쿼리 입력.
    3. 입력 직후 page.input_value("#sb_form_q") 를 읽어
       - 잔존 텍스트("OLDTEXT") 가 남지 않고
       - 값이 쿼리와 정확히 일치(중복/덧붙임 없음) 하는지 검증.
    4. 스크린샷 증거를 /tmp 에 저장.

주의: 제품은 headed Chrome(CDP attach) 이나, fill 동작은 headless 와 동일하므로
headless Chromium 으로 재현 검증한다 (표시장치 부재 환경).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from core.humanizer import Humanizer  # noqa: E402

QUERY = "qwen3.8에 대한 심층 분석"
LEFT_OVER = "OLDTEXT"
SELECTOR = "#sb_form_q"
SHOT_PATH = "/tmp/bing_clear_verify.png"


def main() -> int:
    exit_code = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.bing.com", timeout=30000)
        page.wait_for_selector(SELECTOR, timeout=15000)

        # 1) 잔존 텍스트 시뮬레이션(이전 세션 잔존 가정).
        page.click(SELECTOR)
        page.keyboard.type(LEFT_OVER)
        before = page.input_value(SELECTOR)
        print(f"[verify] 잔존 텍스트 입력 후 value = {before!r}")

        # 2) 실제 제품 코드로 쿼리 입력 (typo_prob=0 → 오타 없는 순수 입력).
        humanizer = Humanizer()
        humanizer.type_text_with_typos(page, SELECTOR, QUERY, typo_prob=0.0)

        # 3) 입력 직후 실제 DOM 값 읽기 (Enter 는 누르지 않음 — 값 보존).
        after = page.input_value(SELECTOR)
        print(f"[verify] Humanizer 입력 후 value = {after!r}")
        page.screenshot(path=SHOT_PATH)
        print(f"[verify] 스크린샷 저장: {SHOT_PATH}")

        # 4) 검증.
        leaked = LEFT_OVER in after
        exact = after == QUERY
        no_dup = QUERY not in after.replace(QUERY, "", 1)  # 쿼리 자체가 1회만
        print(f"[verify] 잔존누수={leaked} / 정확일치={exact} / 중복없음={no_dup}")

        if leaked or not exact or not no_dup:
            print("[verify] FAIL — 중복 입력 또는 잔존 텍스트 발견")
            exit_code = 1
        else:
            print("[verify] PASS — 중복 입력 없음 (fill 강제 클리어 확인)")

        browser.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
