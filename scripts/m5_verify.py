"""M5 검증: pipe 모드 Chrome 기동 → 포트미개방+알림없음+webdriver=False+검색성공.

로컬 실행 전용 (위임 불필요). 로컬 LLM 과부하 회피 목적.
"""
from __future__ import annotations

import json
import subprocess
import time

from core.cdp_bridge import CDPBridge
from core.search import SearchDispatcher, SearchConfig
from core.humanizer import Humanizer

logger = __import__("logging").getLogger("m5_verify")


def main() -> dict:
    port = 9223
    profile = "m5verify"
    results: dict = {
        "port_open": None,
        "alert_none": None,
        "webdriver_false": None,
        "search_ok": None,
    }

    # 1. CDPBridge(pipe) 가 알아서 Chrome spawn
    bridge = CDPBridge(port=port, profile_name=profile, transport="pipe", headless=False)
    bridge.connect()
    time.sleep(2)

    try:
        # 2. 포트 개방 확인 (사용 port 가 열려선 안 됨)
        lsof = subprocess.run(["lsof", "-i", f":{port}"], capture_output=True, text=True)
        results["port_open"] = len(lsof.stdout.strip()) > 0

        # 알림 여부: 프로세스 인자에 --remote-debugging-port 가 없는지 확인
        ps = subprocess.run(["ps", "aux"], capture_output=True, text=True).stdout
        chrome_lines = [l for l in ps.splitlines() if "Google Chrome" in l and "Helper" not in l]
        results["alert_none"] = all("--remote-debugging-port" not in l for l in chrome_lines)

        # 3. webdriver 확인
        wd = bridge.page.evaluate("() => navigator.webdriver")
        results["webdriver_false"] = (wd is False)
        logger.info("navigator.webdriver = %s", wd)

        # 4. 검색 1회 (DDG, 구글제외)
        humanizer = Humanizer()
        disp = SearchDispatcher(SearchConfig(engine="duckduckgo", enable_google=False))
        tag, out = disp.search(bridge.page, humanizer, "test query m5 verify")
        results["search_ok"] = len(out.get("results", [])) > 0
        logger.info("search(%s) results = %d", tag, len(out.get("results", [])))

        bridge.disconnect()
    except Exception as exc:  # noqa: BLE001
        logger.exception("검증 중 오류: %s", exc)
        results["error"] = str(exc)
    finally:
        if bridge._process is not None:
            bridge._process.terminate()
            try:
                bridge._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                bridge._process.kill()

    return results


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)
    res = main()
    with open("/tmp/m5_verify.json", "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))
