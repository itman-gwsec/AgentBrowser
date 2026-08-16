"""M2 실제검증: 실제 Chromium(headless)에서 위키백과 문서의 링크 셀렉터로
move_mouse_to_element(page, selector, click=True) 를 호출 → 커서가 링크 중심으로
이동한 뒤 해당 위치에서 클릭되는지 관찰한다.

(DuckDuckGo/Bing 등은 봇 챌린지로 자동접근이 차단되어, 봇친화적인 위키백과를
실제 검증 대상으로 사용한다. mousemove/click 좌표는 페이지 훅으로 캡처.)

결과는 /tmp/m2_verify.json 에 저장:
  - target_selector: 대상 셀렉터
  - computed_center: move_mouse_to_element 가 반환한 중심좌표 (cx, cy)
  - moved_success: (마지막 mousemove 가 중심 근처) AND (click 이 중심에서 링크에 발생)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/Volumes/Data_Vault/ExoCortex/Projects/AgentBrowser")
sys.path.insert(0, str(ROOT / "src"))

from core.humanizer import Humanizer, HumanizerConfig  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

RESULT: dict = {
    "target_selector": None,
    "computed_center": None,
    "moved_success": False,
    "details": {},
}

TARGET_URL = "https://en.wikipedia.org/wiki/Python_(programming_language)"
SELECTOR = "#bodyContent a[href^='/wiki/']"  # 문서 본문의 실제 하이퍼링크


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(TARGET_URL, wait_until="domcontentloaded")
        page.wait_for_selector(SELECTOR, state="attached", timeout=20000)
        # 첫 번째 링크가 뷰포트 내에 오도록 대기(위키는 긴 문서).
        page.wait_for_timeout(1000)

        # mousemove/click 를 캡처하는 훅 설치. 링크 클릭 기본동작(이동)은 방지하여
        # 클릭이 링크 중심에서 발생했는지 좌표로 판별한다.
        page.evaluate(
            """() => {
                window.__moves = [];
                window.__click = null;
                document.addEventListener('mousemove', (e) => {
                    window.__moves.push([e.clientX, e.clientY]);
                }, true);
                document.addEventListener('click', (e) => {
                    const a = e.target.closest('a');
                    window.__click = {
                        x: e.clientX, y: e.clientY,
                        href: a ? a.href : null,
                    };
                    if (a) e.preventDefault();  // 이동 방지 → 페이지 유지
                }, true);
            }"""
        )

        humanizer = Humanizer(HumanizerConfig(mouse_steps=20))
        center = humanizer.move_mouse_to_element(page, SELECTOR, click=True)

        moves = page.evaluate("() => window.__moves")
        click = page.evaluate("() => window.__click")
        browser.close()

    final_move = moves[-1] if moves else None
    RESULT["target_selector"] = SELECTOR
    RESULT["computed_center"] = [round(center[0], 1), round(center[1], 1)] if center else None

    moved = False
    if final_move and center:
        dx = abs(final_move[0] - center[0])
        dy = abs(final_move[1] - center[1])
        moved = dx <= 6.0 and dy <= 6.0  # 지터 포함 오차범위
    click_ok = bool(
        click
        and center
        and abs(click["x"] - center[0]) <= 6.0
        and abs(click["y"] - center[1]) <= 6.0
    )
    RESULT["moved_success"] = bool(moved and click_ok)
    RESULT["details"] = {
        "target_url": TARGET_URL,
        "final_mousemove": final_move,
        "click_event": click,
        "num_mousemoves": len(moves),
        "mouse_at_center_tolerance_px": 6.0,
        "note": "DuckDuckGo/Bing 차단으로 위키백과를 실제 검증 대상으로 사용.",
    }


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 검증 실패 원인 보존.
        RESULT["details"]["error"] = f"{type(exc).__name__}: {exc}"
        RESULT["moved_success"] = False
    out = Path("/tmp/m2_verify.json")
    out.write_text(json.dumps(RESULT, ensure_ascii=False, indent=2))
    print(json.dumps(RESULT, ensure_ascii=False, indent=2))
