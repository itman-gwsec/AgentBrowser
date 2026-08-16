"""엔진별 인간유사 검색 모듈 (Engine-specific human-like search).

검색 엔진(Google / DuckDuckGo / Bing)별로 인간과 유사한 검색 동작을 수행한다.
실제(헤드풀) Chrome 은 UA/WebGL/지문이 이미 인간과 동일하므로, 남은 봇 탐지
회피 변수는 **동작 패턴**뿐이다. 따라서 ``Humanizer``(타이핑·생각대기·궤적)와
조합하여 검색창에 한 글자씩 입력하고 Enter 를 누르는 방식을 택한다.

설계 제약 (IDEA.md / design doc §4):
- 익스텐션(JS) 회피 로직은 일절 포함하지 않는다. Python agent 레이어에서만 구현.
- ``time.sleep`` 을 제거하지 않는다 — 인간 리듬 그 자체가 목적이기 때문.
- 캡차 탐지는 ``core.cdp_bridge.CDPBridge.detect_and_request_hitl`` 을 **재사용**한다
  (단일 책임: 본 모듈은 검색 수행에만 집중, 캡차 탐지는 cdp_bridge 가 담당).

MVP 범위 (이번 위임):
- 엔진별 가중치(B)는 제외 — 기본 동일 동작만 구현.
- 결과 파싱/추출 완료: ``page.evaluate`` JS 로 엔진별 셀렉터→범용 fallback 으로
  링크(타이틀+URL) N개를 추출해 ``[search:{engine}] query='...' results=N``
  형태로 요약. ``humanizer.pick_click_depth()`` 기반 무작위 클릭 부수효과 포함.
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, Field, model_validator

from core.handoff import HITLRequest
from core.humanizer import Humanizer
from core.session_log import SearchLogEntry, SessionLog

if TYPE_CHECKING:
    # 런타임 의존성(playwright) 없이 타입만 참조 — 순환 import 방지.
    from core.cdp_bridge import CDPBridge

# 모듈 전역 로거 (print 금지, 일관성 유지).
logger = logging.getLogger(__name__)


class SearchConfig(BaseModel):
    """검색 엔진 설정 (pydantic v2).

    - ``engine``: 사용할 검색 엔진 (기본은 관대한 DuckDuckGo).
    - ``query_param``: 엔진별 쿼리 키 매핑 (google/ddg/bing 모두 "q").
    - ``result_wait_min_s/max_s``: 검색 후 결과 로드 대기 범위(초).
      min > max 이면 ``model_validator`` 가 거부한다 (min/max 제약).
    """

    # 사용할 검색 엔진. 기본은 봇 차단이 가장 관대한 DDG.
    engine: Literal["google", "duckduckgo", "bing"] = "duckduckgo"

    # google 엔진 활성화 스위치 (기본 비활성). True 로 명시해야만 engine='google' 선택 가능.
    # 보안/정책상 google 은 기본 꺼져 있으며, _select_engine 에서 False 시 ValueError 로 차단.
    enable_google: bool = False

    # 엔진별 쿼리 파라미터 키 매핑.
    query_param: dict[str, str] = Field(
        default_factory=lambda: {"google": "q", "duckduckgo": "q", "bing": "q"}
    )

    # 검색 후 결과 로드 대기(초) — 인간은 즉시 다음 동작을 하지 않음.
    result_wait_min_s: float = Field(default=1.0, ge=0.0, description="결과 대기 최소(초)")
    result_wait_max_s: float = Field(default=3.0, ge=0.0, description="결과 대기 최대(초)")

    # 엔진별 인간유사 동작 배율 (typing/pause/scroll/wait).
    # google 은 감시가 엄격하므로 배율을 높여 리듬을 늦추고, ddg 는 기준(1.0),
    # bing 은 중간값. 기존 필드와 충돌하지 않도록 extra=forbid 유지.
    engine_weights: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "google": {"typing_x": 1.4, "pause_x": 1.6, "scroll_x": 1.5, "wait_x": 1.5},
            "duckduckgo": {"typing_x": 1.0, "pause_x": 1.0, "scroll_x": 1.0, "wait_x": 1.0},
            "bing": {"typing_x": 1.2, "pause_x": 1.3, "scroll_x": 1.2, "wait_x": 1.2},
        }
    )

    # min <= max 불변식 검증 (pydantic v2 model_validator).
    @model_validator(mode="after")
    def _check_wait_bounds(self) -> SearchConfig:
        """result_wait_min_s 가 max_s 보다 크면 거부한다."""
        if self.result_wait_min_s > self.result_wait_max_s:
            msg = (
                f"result_wait_min_s({self.result_wait_min_s}) 는 "
                f"result_wait_max_s({self.result_wait_max_s}) 보다 클 수 없습니다."
            )
            raise ValueError(msg)
        return self

    # 모델 직렬화/복사 시 추가 필드 거부.
    model_config = {"extra": "forbid"}


class SearchEngine(ABC):
    """검색 엔진 추상 베이스 (OOP 표준: 캡슐화·타입힌트·로거).

    하위 클래스는 ``engine_name`` / ``base_url`` 을 오버라이드하고
    ``search()`` 를 구현한다. 공통 네비게이션/대기 로직은 본 베이스가 제공한다.
    """

    # 하위 클래스가 오버라이드할 엔진 메타데이터.
    engine_name: str = "base"
    base_url: str = ""

    # 엔진별 결과 링크 정밀 셀렉터. 빈 문자열이면 범용 fallback 을 사용한다
    # (베이스 기본값). 하위 클래스가 자신의 결과 카드 셀렉터로 오버라이드한다.
    _RESULT_SELECTOR: ClassVar[str] = ""

    def __init__(self, config: SearchConfig) -> None:
        """설정을 보관한다.

        Args:
            config: 검색 설정 (엔진/쿼리키/대기범위).
        """
        self.config: SearchConfig = config
        logger.debug("SearchEngine(%s) 초기화", self.engine_name)

    @abstractmethod
    def search(
        self, page: object, humanizer: Humanizer, query: str
    ) -> tuple[str, dict[str, Any]]:
        """페이지 이동 → 인간유사 검색 → (요약, 메타) 튜플을 반환한다.

        Args:
            page: Playwright page 객체 (런타임 타입 Any).
            humanizer: 인간유사 동작 엔진 (타이핑·생각대기).
            query: 검색어.

        Returns:
            ``(summary, meta)`` 튜플.
            - summary: 검색 결과 요약 문자열 (엔진/쿼리/결과 포함).
            - meta: 로깅용 메타 ``{"url": str, "results_count": int,
              "click_depth": int}``.
        """
        raise NotImplementedError

    def _build_url(self, query: str) -> str:
        """엔진별 검색 URL 을 조립한다 (query_param 키 매핑 반영).

        Args:
            query: 검색어 (URL 인코딩 적용).

        Returns:
            ``{base_url}?{key}={encoded_query}`` 형태의 URL.
        """
        key = self.config.query_param.get(self.engine_name, "q")
        return f"{self.base_url}?{key}={quote_plus(query)}"

    def _navigate(self, page: object, url: str) -> None:
        """페이지 이동 후 인간유사 '생각' 대기를 적용한다.

        Args:
            page: Playwright page 객체.
            url: 이동할 검색 URL.
        """
        logger.debug("[%s] navigate -> %s", self.engine_name, url)
        page.goto(url)  # type: ignore[attr-defined]
        # 인간유사: 네비게이션 직후 짧은 생각 대기 (Humanizer 위임).
        # (move_mouse_bezier 주소창 근사 좌표는 생략 — page.goto 사용)
        humanizer = getattr(self, "_humanizer", None)
        if humanizer is not None:
            humanizer.think_pause()

    def _wait_results(self) -> None:
        """검색 후 결과 로드 대기를 적용한다 (config 범위 * 엔진 wait_x)."""
        base = random.uniform(self.config.result_wait_min_s, self.config.result_wait_max_s)
        weight = self.config.engine_weights[self.engine_name]["wait_x"]
        duration = base * weight
        logger.debug("[%s] 결과 대기 (%.2fs, wait_x=%.2f)", self.engine_name, duration, weight)
        time.sleep(duration)

    # 검색 결과 링크 추출용 JS (엔진별 정밀 셀렉터 → 범용 fallback).
    # ``page.evaluate(_LINK_JS, selector)`` 형태로 셀렉터를 인자로 주입한다.
    # selector 가 빈 문자열이면 범용 ``a[href]`` 필터 경로(fallback)를 사용한다.
    _LINK_JS: ClassVar[str] = (
        "(selector) => {"
        "  const anchor = (el) => (el.tagName === 'A' ? el : el.closest('a'));"
        "  const nodes = selector"
        "    ? Array.from(document.querySelectorAll(selector)).map(anchor).filter(Boolean)"
        "    : Array.from(document.querySelectorAll('a[href]')).filter("
        "        (a) => a.href.startsWith('http') && a.innerText.trim());"
        "  const out = [];"
        "  const seen = new Set();"
        "  for (const a of nodes) {"
        "    const url = a.href || '';"
        "    let title = (a.innerText || a.title || '').trim();"
        "    if (!title) {"
        "      const head = a.querySelector('h3, h2');"
        "      title = head ? (head.innerText || head.textContent || '').trim() : '';"
        "    }"
        "    if (!url.startsWith('http') || !title || seen.has(url)) continue;"
        "    seen.add(url);"
        "    out.push({title: title.slice(0, 80), url});"
        "  }"
        "  return out.slice(0, 10);"
        "}"
    )

    def _evaluate_links(self, page: object, selector: str) -> list:
        """JS 를 평가해 원시 링크 리스트를 반환한다 (평가 실패 시 빈 리스트).

        Args:
            page: Playwright page 객체.
            selector: 정밀 셀렉터. 빈 문자열이면 JS 내부 범용 fallback 경로.

        Returns:
            JS 가 반환한 원시 리스트. 실패/비리스트면 ``[]``.
        """
        try:
            raw = page.evaluate(self._LINK_JS, selector)  # type: ignore[attr-defined]
        except Exception:  # JS 평가 실패 등 — 결과 없음으로 간주.
            logger.debug("[%s] 결과 링크 추출 실패 — 빈 결과", self.engine_name)
            return []
        return raw if isinstance(raw, list) else []

    def _extract_links(self, page: object) -> list[dict]:
        """결과 페이지에서 링크(타이틀+URL)를 추출한다 (엔진별 셀렉터 분기).

        ``self._RESULT_SELECTOR`` (엔진별 정밀 셀렉터)를 JS 인자로 넘겨 광고/
        관련검색 등 잡음 링크를 배제한다. 셀렉터가 비어 있거나(베이스) 정밀
        셀렉터가 0건이면 범용 ``a[href]`` fallback 으로 자동 재시도한다.

        Args:
            page: Playwright page 객체.

        Returns:
            ``[{"title": str, "url": str}, ...]`` 형태의 링크 리스트(최대 10).
        """
        selector = self._RESULT_SELECTOR
        raw = self._evaluate_links(page, selector)
        if not raw and selector:
            # 정밀 셀렉터 미매칭(레이아웃 변경 등) — 범용 fallback 으로 재시도.
            logger.debug("[%s] 정밀 셀렉터 0건 — 범용 fallback 재시도", self.engine_name)
            raw = self._evaluate_links(page, "")
        links: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url.startswith("http"):
                continue
            title = str(item.get("title", "")).strip()
            if title:
                links.append({"title": title[:80], "url": url})
        return links[:10]

    def _apply_click_depth(self, page: object, humanizer: Humanizer, links: list[dict]) -> int:
        """결과 링크를 인간처럼 훑는(hover/새탭) 부수효과를 시뮬레이션한다.

        ``humanizer.pick_click_depth()`` 로 깊이를 정하고, 해당 개수만큼 결과
        링크를 무작위 선택해 **즉시 이동(page.goto) 대신** 다음과 같이 행동한다:
            - ``page.evaluate``(getBoundingClientRect)로 링크 중심 좌표를 얻어
              ``humanizer.move_mouse_bezier`` 베지어 이동으로 마우스를 올림(hover).
            - depth 중 정확히 1개(첫 선택)만 새 탭(``page.context.new_page``)에서
              열어 **개별 사이트에서도 humanizer(스크롤/체류/마우스)를 적용**한 뒤
              즉시 닫는다 (인간이 링크를 훑어보고 닫는 행위 + 개별 사이트 봇 탐지/Cloudflare 대비).
            - 나머지는 hover 만 수행.
        이는 서버측 패턴 완화용 **부수효과**일 뿐, 결과 요약에는 영향 없다.
        좌표 획득/이동/새탭 실패는 모두 무시(try/except).

        Args:
            page: Playwright page 객체.
            humanizer: 인간유사 동작 엔진 (move_mouse_bezier/think_pause).
            links: 추출된 결과 링크 리스트.

        Returns:
            실제 적용된 클릭 깊이(int, 0 이상). 로깅용 meta 에 사용.
        """
        # pick_click_depth 는 정상 경로에서 int 를 반환하나 방어적 int 캐스팅.
        depth = int(humanizer.pick_click_depth())
        logger.debug("[%s] 클릭 깊이 선택 (depth=%d)", self.engine_name, depth)
        if depth <= 0 or not links:
            return 0
        # depth 개를 중복 없이 무작위 선택.
        chosen = random.sample(links, min(depth, len(links)))
        for idx, item in enumerate(chosen):
            url = item["url"]
            # 링크를 식별할 셀렉터 후보 (a[href=...], 미매칭 시 hover 실패 무시).
            selector = f"a[href='{url}']"
            try:
                # 클릭 전 인간유사 '생각' 대기 적용.
                humanizer.think_pause()
                # 셀렉터 요소의 중심으로 마우스를 곡선 이동(hover 흉내).
                # move_mouse_to_element 가 내부에서 boundingBox→중심 계산→
                # 베지어 이동까지 수행한다 (시작점은 추적 중인 현재 커서 위치).
                center = humanizer.move_mouse_to_element(page, selector)
                if center is None:
                    # 좌표 획득 실패는 무시(try/except 로 감싸져 있음).
                    logger.debug(
                        "[%s] 링크 중심 획득 실패(무시) -> %s", self.engine_name, url
                    )
                # depth 중 정확히 1개(첫 선택)만 새 탭에서 열었다 닫기.
                if idx == 0 and getattr(page, "context", None) is not None:
                    new_tab = page.context.new_page()  # type: ignore[attr-defined]
                    try:
                        new_tab.goto(url)  # type: ignore[attr-defined]
                        # Bug B 수정: 결과 페이지뿐 아니라 **이동한 개별 사이트(새 탭)**에서도
                        # humanizer 를 적용한다. 개별 사이트도 봇 탐지(Cloudflare challenge 등)를
                        # 하므로, 새 탭에서 스크롤/체류/마우스 행동을 수행해 인간 흉내를 낸다.
                        humanizer.scroll_to_bottom(new_tab, scrolls=2)
                        humanizer.think_pause()
                        # 마우스 이동 몇 회 (인간이 페이지를 훑는 행위).
                        # center 는 결과 페이지 링크의 중심좌표(없으면 0,0).
                        bx = float(center[0]) if center is not None else 0.0
                        by = float(center[1]) if center is not None else 0.0
                        humanizer.move_mouse_bezier(new_tab, 0, 0, bx, by)
                        humanizer.think_pause()
                    except Exception:  # challenge 페이지 등 — 크래시 없이 무시.
                        logger.debug(
                            "[%s] 새 탭 humanizer 적용 실패(무시) -> %s",
                            self.engine_name,
                            url,
                        )
                    finally:
                        new_tab.close()  # type: ignore[attr-defined]
                    logger.info(
                        "[%s] 새 탭 훑기+humanizer 시뮬레이션(닫음) -> %s",
                        self.engine_name,
                        url,
                    )
                else:
                    # 나머지는 hover 만 (마우스가 이미 위에 올라가 있음).
                    page.hover(selector)  # type: ignore[attr-defined]
                    logger.info("[%s] 결과 링크 hover 시뮬레이션 -> %s", self.engine_name, url)
            except Exception:  # 좌표/이동/새탭 실패 — 무시.
                logger.debug("[%s] 링크 훑기 실패(무시) -> %s", self.engine_name, url)
        return depth

    def _post_search(
        self, page: object, humanizer: Humanizer, query: str
    ) -> tuple[str, dict[str, Any]]:
        """결과 대기→스크롤→링크 추출→클릭 시뮬→(요약, 메타) 반환 (공통 후처리).

        Args:
            page: Playwright page 객체.
            humanizer: 인간유사 동작 엔진.
            query: 검색어.

        Returns:
            ``(summary, meta)`` 튜플.
            - summary: 결과 링크를 포함한 요약 문자열.
            - meta: ``{"url": str, "results_count": int, "click_depth": int}``.
        """
        self._wait_results()
        weights = self.config.engine_weights[self.engine_name]
        # 결과 훑기 전 짧은 체류 (인간이 화면을 인식하는 찰나).
        humanizer.think_pause()
        # 하단까지 확정적으로 여러 회 스크롤 (인간이 결과 목록을 훑는 행위).
        humanizer.scroll_to_bottom(page, scrolls=4, scroll_x=weights["scroll_x"])
        # 결과 읽기 체류 (인간이 링크를 훑으며 머무름).
        humanizer.think_pause()
        # 검색 결과 페이지에서 링크 추출 (클릭 전 스냅샷 확보).
        links = self._extract_links(page)
        # 인간유사 클릭 부수효과 (결과 요약에는 영향 없음) — 적용 깊이 반환.
        depth = self._apply_click_depth(page, humanizer, links)
        # 추출한 링크 스냅샷 기준 요약 반환 (클릭 후 재파싱 방지).
        summary = self._summarize(page, query, links=links)
        # 마무리 체류 (인간이 검색 세션을 끝맺는 머무름).
        humanizer.think_pause()
        # 로깅용 메타 구성 (dispatcher 가 SessionLog 에 기록).
        meta: dict[str, Any] = {
            "url": str(getattr(page, "url", "")),
            "results_count": len(links),
            "click_depth": depth,
        }
        return summary, meta

    def _summarize(self, page: object, query: str, links: list[dict] | None = None) -> str:
        """검색 결과 요약 문자열을 반환한다 (실제 파싱).

        ``page.evaluate`` 로 추출한 결과 링크(타이틀+URL)를 포함한
        ``[search:{engine}] query='...' results=N\\n - {title} ({url})...``
        형태의 요약을 생성한다.

        Args:
            page: Playwright page 객체 (링크 추출용).
            query: 검색어.
            links: 미리 추출된 링크 리스트. ``None`` 이면 page 에서 재추출.

        Returns:
            결과 링크를 포함한 검색 요약 문자열.
        """
        if links is None:
            links = self._extract_links(page)
        n = len(links)
        lines = [f"[search:{self.engine_name}] query='{query}' results={n}"]
        for item in links:
            title = item.get("title", "")
            url = item.get("url", "")
            lines.append(f" - {title} ({url})")
        summary = "\n".join(lines)
        logger.debug("검색 요약(%d건):\n%s", n, summary)
        return summary


class GoogleSearch(SearchEngine):
    """Google 검색 (엔진별 selector 변동 대비 + URL 쿼리 fallback)."""

    engine_name = "google"
    base_url = "https://www.google.com/search"

    # Google 결과 카드 링크: h3 제목 앵커 우선(div.g a h3 / #search a h3 → closest('a')),
    # 미매칭 시 결과 카드 앵커(div.g a). 광고(div.uEierd)·관련검색은 자연 배제.
    _RESULT_SELECTOR: ClassVar[str] = "div.g a h3, #search a h3, div.g a"

    def search(self, page: object, humanizer: Humanizer, query: str) -> tuple[str, dict[str, Any]]:
        """Google 검색 수행.

        URL 쿼리 방식으로 우선 이동(fallback 항상 보장)한 뒤, 인간유사 타이핑으로
        검색창(#searchbox/textarea)에 입력하고 Enter 를 누른다. Google 이 selector 를
        바꿀 수 있으므로 타자 단계는 예외 허용(실패해도 URL 결과 유지).
        """
        self._humanizer = humanizer  # _navigate 에서 think_pause 위임용.
        # 엔진별 배율(google 은 감시 엄격 → typing/pause/scroll/wait 모두 상향).
        weights = self.config.engine_weights[self.engine_name]
        # 1) URL 쿼리 방식 이동 (selector 변동과 무관하게 결과 확보).
        self._navigate(page, self._build_url(query))
        # 2) 인간유사: 검색창에 한 글자씩 입력 후 Enter (예외 허용).
        try:
            humanizer.type_text_with_typos(
                page,
                "textarea[name=q], input[name=q]",
                query,
                typo_prob=0.15,
                typing_x=weights["typing_x"],
                pause_x=weights["pause_x"],
            )
            page.keyboard.press("Enter")  # type: ignore[attr-defined]
        except Exception:  # selector 미존재 등 — URL 쿼리 결과로 대체.
            logger.debug("[google] 검색창 selector 미존재 — URL 쿼리 결과 유지")
        # 3) 결과 로드 대기 후 확률적 스크롤(엔진별 scroll_x 반영).
        return self._post_search(page, humanizer, query)


class DuckDuckGoSearch(SearchEngine):
    """DuckDuckGo 검색 (관대한 엔진 — 기본값)."""

    engine_name = "duckduckgo"
    base_url = "https://duckduckgo.com/"

    # DDG 결과 제목 앵커: 신규 SPA(data-testid) + 구 HTML 버전(result__a).
    _RESULT_SELECTOR: ClassVar[str] = 'a[data-testid="result-title-a"], a.result__a'

    def search(self, page: object, humanizer: Humanizer, query: str) -> tuple[str, dict[str, Any]]:
        """DuckDuckGo 검색 수행.

        URL 쿼리 방식으로 이동한 뒤, ``#searchbox`` 에 인간유사 타이핑 후 Enter.
        """
        self._humanizer = humanizer
        weights = self.config.engine_weights[self.engine_name]
        self._navigate(page, self._build_url(query))
        try:
            humanizer.type_text_with_typos(
                page,
                "#searchbox",
                query,
                typo_prob=0.15,
                typing_x=weights["typing_x"],
                pause_x=weights["pause_x"],
            )
            page.keyboard.press("Enter")  # type: ignore[attr-defined]
        except Exception:
            logger.debug("[ddg] 검색창 selector 미존재 — URL 쿼리 결과 유지")
        return self._post_search(page, humanizer, query)


class BingSearch(SearchEngine):
    """Bing 검색."""

    engine_name = "bing"
    base_url = "https://www.bing.com/search"

    # Bing 유기적 결과(li.b_algo)의 h2 제목 앵커만 선택 — 광고(li.b_ad) 배제.
    _RESULT_SELECTOR: ClassVar[str] = "li.b_algo h2 a"

    def search(self, page: object, humanizer: Humanizer, query: str) -> tuple[str, dict[str, Any]]:
        """Bing 검색 수행.

        URL 쿼리 방식으로 이동한 뒤, ``#sb_form_q`` 에 인간유사 타이핑 후 Enter.
        """
        self._humanizer = humanizer
        weights = self.config.engine_weights[self.engine_name]
        self._navigate(page, self._build_url(query))
        try:
            humanizer.type_text_with_typos(
                page,
                "#sb_form_q",
                query,
                typo_prob=0.15,
                typing_x=weights["typing_x"],
                pause_x=weights["pause_x"],
            )
            page.keyboard.press("Enter")  # type: ignore[attr-defined]
        except Exception:
            logger.debug("[bing] 검색창 selector 미존재 — URL 쿼리 결과 유지")
        return self._post_search(page, humanizer, query)


class SearchDispatcher:
    """검색 엔진 디스패처 (engine 선택 → search → 캡차 HITL 처리).

    ``config.engine`` 에 따라 적절한 ``SearchEngine`` 을 선택하고 ``search()`` 를
    호출한다. 검색 후 ``cdp_bridge.detect_and_request_hitl()`` 을 재사용하여 캡차를
    탐지하며, 탐지 시 ``HITLRequest`` 를, 정상 시 결과 요약 문자열을 반환한다.
    """

    # engine 이름 → 구현 클래스 매핑 (명확한 선택 로직).
    _ENGINE_MAP: ClassVar[dict[str, type[SearchEngine]]] = {
        "google": GoogleSearch,
        "duckduckgo": DuckDuckGoSearch,
        "bing": BingSearch,
    }

    def __init__(
        self,
        config: SearchConfig | None = None,
        humanizer: Humanizer | None = None,
        cdp_bridge: CDPBridge | None = None,
    ) -> None:
        """설정/인간유사엔진/CDP브리지를 보관한다.

        Args:
            config: 검색 설정. 미지정 시 ``SearchConfig()`` 기본값.
            humanizer: 인간유사 동작 엔진. 미지정 시 ``Humanizer()`` 기본값.
            cdp_bridge: 캡차 탐지 재사용용 CDP 브리지. 미지정 시 캡차 탐지 생략.
        """
        self.config: SearchConfig = config if config is not None else SearchConfig()
        self.humanizer: Humanizer = humanizer if humanizer is not None else Humanizer()
        self.cdp_bridge: CDPBridge | None = cdp_bridge
        # 검색 세션 로그 (지연/공유 없이 인스턴스별 기본 경로 사용).
        self.session_log: SessionLog = SessionLog()
        logger.debug("SearchDispatcher 초기화 (engine=%s)", self.config.engine)

    def _select_engine(self) -> SearchEngine:
        """config.engine 에 매핑된 SearchEngine 인스턴스를 반환한다.

        google 은 보안/정책상 기본 비활성. ``enable_google=False`` 이면서
        ``engine='google'`` 이면 명시적으로 ``ValueError`` 로 차단한다.
        """
        # google 은 기본 비활성 스위치로 보호 — 활성화 플래그가 필요하다.
        if self.config.engine == "google" and not self.config.enable_google:
            msg = "google engine is disabled; set SearchConfig.enable_google=True to use it"
            logger.warning("engine 선택 거부 (enable_google=False): %s", msg)
            raise ValueError(msg)
        engine_cls = self._ENGINE_MAP[self.config.engine]
        return engine_cls(self.config)

    def _compute_dynamic_weights(self) -> dict[str, dict[str, float]]:
        """세션 로그(중복쿼리비율) 기반으로 engine_weights 를 동적으로 보정한다.

        ``duplicate_query_ratio(window=20)`` 가 높을수록 인간처럼(지연↑) 행동하도록
        모든 엔진의 typing/pause/scroll/wait 배율을 ``factor`` 만큼 선형 증가시킨다.
        ``factor = 1.0 + min(dup_ratio, 0.5) * 0.6`` (dup_ratio=0.5 → 1.3배, 상한 2.0).
        """
        # 기본값 복사 (원본 config 는 변경하지 않도록 새 dict 생성).
        base: dict[str, dict[str, float]] = {
            engine: dict(weights)
            for engine, weights in self.config.engine_weights.items()
        }
        dup_ratio = self.session_log.duplicate_query_ratio(window=20)
        # dup_ratio 가 높을수록 factor 증가 (0 → 1.0배, 0.5+ → 1.3배 상한).
        factor = 1.0 + min(dup_ratio, 0.5) * 0.6
        # 보정된 배율 = 기본 * factor, 개별 상한 2.0 적용.
        corrected: dict[str, dict[str, float]] = {}
        for engine, weights in base.items():
            corrected[engine] = {k: min(v * factor, 2.0) for k, v in weights.items()}
        logger.debug(
            "동적 가중치 보정: factor=%.3f (dup_ratio=%.3f)", factor, dup_ratio
        )
        return corrected

    def run(self, page: object, query: str) -> str | HITLRequest:
        """검색을 수행하고 결과 문자열 또는 캡차 HITLRequest 를 반환한다.

        플로우:
        1. engine 선택 → ``search()`` 호출 (humanizer 연동 포함).
        2. ``cdp_bridge`` 가 있으면 캡차 탐지 재사용 — 탐지 시 ``HITLRequest`` 반환.
        3. 미탐지/브리지 없으면 결과 요약 문자열 반환.

        Args:
            page: Playwright page 객체 (검색 대상 탭).
            query: 검색어.

        Returns:
            캡차 탐지 시 ``HITLRequest``, 정상 시 결과 요약 ``str``.
        """
        # 세션 로그 기반 동적 보정: 매 검색마다 최신 로그 반영하여 engine_weights 재계산.
        # pydantic 모델은 직접 필드 대입 대신 model_copy 로 불변 갱신 (engine 선택 전 세팅).
        dynamic = self._compute_dynamic_weights()
        self.config = self.config.model_copy(update={"engine_weights": dynamic})
        logger.debug("run() 진입 — 동적 engine_weights 보정 완료")

        engine = self._select_engine()
        logger.debug("engine 선택: %s (query=%r)", engine.engine_name, query)

        # 세션 간격 대기 — 연속 검색 세션 패턴을 인간처럼 띄엄띄엄 끊는다.
        self.humanizer.session_gap()

        # search() 는 (summary, meta) 튜플 반환 — meta 는 로깅용.
        result: str
        result, meta = engine.search(page, self.humanizer, query)

        # 다음 쿼리 변형 준비 (서버측 패턴 완화용) — 로깅만, 반환값은 기존 유지.
        self.humanizer.vary_query(query)

        # 캡차 탐지: cdp_bridge.detect_and_request_hitl() 재사용 (단일 책임).
        if self.cdp_bridge is not None:
            hitl = self.cdp_bridge.detect_and_request_hitl()
            if hitl is not None:
                logger.info("캡차 탐지 — HITLRequest 반환 (%s)", hitl.reason)
                return hitl

        # 검색 성공 시 세션 로그에 기록 (중복 쿼리 비율 등 후속 판단 지표).
        # 로깅 실패는 검색 결과 반환에 영향주지 않도록 격리.
        try:
            self.session_log.append(
                SearchLogEntry(
                    engine=self.config.engine,
                    query=query,
                    url=str(meta.get("url", "")),
                    results_count=int(meta.get("results_count", -1)),
                    click_depth=int(meta.get("click_depth", 0)),
                )
            )
        except Exception:
            logger.debug("세션 로그 기록 실패 (무시)")

        return result
