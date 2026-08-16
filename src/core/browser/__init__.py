"""헤드풀(화면 있는) 크롬 실행 스텁.

이 모듈은 AgentBrowser 프로젝트의 브라우저 실행 진입점(stub)이다.
- R1(헤드풀 실제 크롬) 원칙: headless=False 를 고정한다. 헤드리스는 인간 유사
  동작·시각적 협업과 모순되어 채택하지 않는다.
- 봇회피 금지: 본 함수에는 봇 탐지 회피 로직(지터·궤적·UA 변조 등)을 일절
  포함하지 않는다. 회피는 헤드풀 환경 + 인간 유사 동작(agent 레이어 책임, IDEA.md §4)
  로 담당하며, 여기서는 단순 launch 만 수행한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# 런타임 import 는 함수 내부에서 수행하므로, 타입 힌트용으로만 선언한다.
if TYPE_CHECKING:
    from playwright.sync_api import Browser


def launch_headed_chrome() -> Browser:
    """헤드풀(화면 있는) 크롬을 실행하고 Browser 객체를 반환한다.

    - Playwright sync API(sync_playwright)를 사용한다.
    - headless=False 를 고정한다(헤드리스 금지 원칙, R1).
    - 봇회피 로직은 포함하지 않는다. 인간유사동작(타이밍 지터 등)은
      agent 레이어 책임(IDEA.md §4)이므로 여기서 처리하지 않는다.
    - Playwright 미설치 시 RuntimeError 로 설치 안내를 던진다.

    Returns:
        Playwright Browser 객체(호출자가 직접 close 해야 함).
    """
    # 런타임 import: 미설치 시 ImportError 가 아닌 안내성 RuntimeError 로 전환.
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(  # noqa: TRY003
            "playwright 가 설치되어 있지 않습니다. 다음으로 설치하세요:\n"
            "  .venv/bin/pip install playwright\n"
            "  .venv/bin/python -m playwright install chromium"
        ) from exc

    # headless=False 고정 — 헤드리스는 R1 원칙과 모순.
    pw = sync_playwright().start()
    browser: Browser = pw.chromium.launch(headless=False)
    return browser
