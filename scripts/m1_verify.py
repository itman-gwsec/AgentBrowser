"""M1 실제 검증: 크롬 종료 상태 → ensure_alive() 자동복구 → 검색 1회 성공.

금지 위반 없음:
- 구글 검색 제외: SearchConfig(engine="duckduckgo") 고정 (enable_google=False).
- 익스텐션 JS 수정 없음: launcher 기본 --load-extension 경로 그대로 사용.
- LLM 능력 부여 없음 / print 금지 (logging 사용).

산출물: /tmp/m1_verify.json
  - before_dead: ensure_alive 호출 전 is_chrome_running 상태
  - after_alive: ensure_alive 호출 후 is_chrome_running 상태
  - recovered: (after_alive and 검색 성공 여부)
  - search_summary: 검색 요약(일부)
"""

from __future__ import annotations

import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("m1_verify")

from core.launcher import is_chrome_running
from core.session import BrowserSession
from core.search import SearchConfig, SearchDispatcher

PORT = 9222
PROFILE = "m1verify"
QUERY = "agentbrowser on-demand chrome recovery test"


def main() -> int:
    before_dead = not is_chrome_running(PORT)
    logger.info("BEFORE: is_chrome_running(9222)=%s (dead_expected=%s)", not before_dead, before_dead)

    # 1) ensure_alive — 죽어 있으면 자동복구(spawn + attach).
    session = BrowserSession(port=PORT, profile_name=PROFILE, startup_timeout_s=30)
    bridge = session.ensure_alive()

    after_alive = is_chrome_running(PORT)
    logger.info("AFTER: is_chrome_running(9222)=%s", after_alive)

    # 2) 검색 1회 (DuckDuckGo 고정, google 제외).
    config = SearchConfig(engine="duckduckgo")
    dispatcher = SearchDispatcher(config=config, cdp_bridge=bridge)
    result = dispatcher.run(bridge.page, QUERY)

    search_ok = isinstance(result, str) and "[search:duckduckgo]" in result
    recovered = bool(after_alive and search_ok)

    summary_preview = result if isinstance(result, str) else f"HITL:{result}"
    logger.info("SEARCH_OK=%s (preview): %s", search_ok, summary_preview[:200])

    payload = {
        "before_dead": before_dead,
        "after_alive": after_alive,
        "recovered": recovered,
        "port": PORT,
        "profile": PROFILE,
        "query": QUERY,
        "search_ok": search_ok,
        "search_summary_preview": summary_preview[:500],
    }
    with open("/tmp/m1_verify.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    logger.info("WROTE /tmp/m1_verify.json recovered=%s", recovered)

    return 0 if recovered else 1


if __name__ == "__main__":
    sys.exit(main())
