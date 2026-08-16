"""DuckDuckGo HTML endpoint 결과 DOM 탐색."""
from __future__ import annotations

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.goto("https://html.duckduckgo.com/html/?q=python+requests+library", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    info = page.evaluate(
        """() => {
            const out = [];
            const anchors = Array.from(document.querySelectorAll("a.result__a"));
            for (const a of anchors.slice(0, 5)) {
                const r = a.getBoundingClientRect();
                out.push({
                    href: a.href.slice(0, 50),
                    text: (a.textContent || "").trim().slice(0, 40),
                    rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                });
            }
            return {count: anchors.length, samples: out};
        }"""
    )
    print("result__a count:", info["count"])
    for i, s in enumerate(info["samples"]):
        print(i, s)
    browser.close()
