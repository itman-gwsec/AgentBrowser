"""엔진별 인간유사 검색 모듈 테스트 (tests/unit/test_search.py).

검증 대상(src/core/search.py):
    - ``SearchConfig`` (pydantic v2) 기본값 및 min/max 제약.
    - ``SearchEngine`` 추상 베이스 + Google/DuckDuckGo/Bing 구현.
    - ``SearchDispatcher`` 의 엔진 선택·캡차(HITL) 반환 로직.

실제 Chrome 기동 금지. ``page`` 와 ``humanizer`` 는 MagicMock 으로 대체하고
``time.sleep`` / ``random`` 을 패치하여 동작(호출 횟수·URL)을 검증한다.

컨벤션: snake_case, 한국어 주석. pytest + unittest.mock.
"""

from __future__ import annotations

from unittest import mock

import pytest
from pydantic import ValidationError

from core.handoff import HITLRequest
from core.search import (
    BingSearch,
    DuckDuckGoSearch,
    GoogleSearch,
    SearchConfig,
    SearchDispatcher,
    SearchEngine,
)

# 실제 세션 로그 (파일 기반) — 신규 동적가중치 테스트 직접 주입용.
# autouse fixture 가 core.search.SessionLog 를 가려도 실제 클래스 사용.
from core.session_log import SearchLogEntry, SessionLog


@pytest.fixture(autouse=True)
def _patch_session_log() -> None:
    """dispatcher.run() 이 실제 logs 파일에 기록하지 않도록 SessionLog 를 대체.

    검색 성공 시 append() 가 호출되는지(동작 경로)는 test_session_log.py 에서
    전담 검증하므로, 여기서는 실제 파일 쓰기만 방지한다. 또한
    duplicate_query_ratio() 는 0.0 을 돌려주어 동적가중치 보정 경로가
    MagicMock 과 비교되지 않도록 한다 (실제 로그 없음 ≡ 중복 0).
    """
    with mock.patch("core.search.SessionLog") as _mock_cls:
        # SessionLog() 인스턴스의 append 는 MagicMock 로 no-op 처리.
        _mock_cls.return_value.append = mock.MagicMock()
        # 중복 비율은 실제 로그 없음을 의미하는 0.0 반환.
        _mock_cls.return_value.duplicate_query_ratio.return_value = 0.0
        yield


def _make_mock_page() -> mock.MagicMock:
    """page.goto / keyboard.press / url 을 가진 mock page."""
    page = mock.MagicMock()
    page.goto = mock.MagicMock()
    page.keyboard.press = mock.MagicMock()
    # page.url 은 Real page 와 유사하게 문자열로 둔다 (요약 반환 시 사용).
    page.url = "https://example.com/results"
    return page


def _make_mock_humanizer() -> mock.MagicMock:
    """Humanizer 의 주요 메서드를 가진 mock humanizer."""
    humanizer = mock.MagicMock()
    humanizer.type_text = mock.MagicMock()
    humanizer.think_pause = mock.MagicMock()
    # pick_click_depth 는 기본값 1 을 반환하도록 설정 (search.py 가 depth<=0 비교 수행).
    # 개별 테스트에서 다른 값이 필요하면 return_value 를 오버라이드한다.
    humanizer.pick_click_depth.return_value = 1
    return humanizer


def test_search_config_default() -> None:
    """SearchConfig 기본값이 명세와 일치한다 (engine=duckduckgo, q 매핑)."""
    cfg = SearchConfig()

    # 기본 엔진은 관대한 DDG.
    assert cfg.engine == "duckduckgo"
    # 엔진별 쿼리 키 매핑 (google/ddg/bing 모두 "q").
    assert cfg.query_param == {"google": "q", "duckduckgo": "q", "bing": "q"}
    # 결과 로드 대기 기본 범위.
    assert cfg.result_wait_min_s == 1.0
    assert cfg.result_wait_max_s == 3.0
    # min <= max 불변식 보장.
    assert cfg.result_wait_min_s <= cfg.result_wait_max_s


def test_search_config_rejects_invalid_bounds() -> None:
    """result_wait_min_s > max_s 이면 pydantic 검증이 실패한다 (min/max 제약)."""
    with pytest.raises(ValidationError):
        SearchConfig(result_wait_min_s=5.0, result_wait_max_s=2.0)


def test_duckduckgo_url() -> None:
    """DuckDuckGoSearch 는 올바른 URL(https://duckduckgo.com/?q=...) 로 goto 한다."""
    cfg = SearchConfig(engine="duckduckgo")
    humanizer = _make_mock_humanizer()
    page = _make_mock_page()

    engine = DuckDuckGoSearch(cfg)
    # sleep 지연 제거 (결과 대기 미수행).
    with mock.patch("core.search.time.sleep"):
        engine.search(page, humanizer, "cats")

    # 올바른 DDG 검색 URL 로 이동했는지 검증.
    page.goto.assert_called_once_with("https://duckduckgo.com/?q=cats")
    # 인간유사(오타 포함) 타이핑도 시도되었는지 확인.
    humanizer.type_text_with_typos.assert_called_once()


def test_dispatcher_selects_engine_runs() -> None:
    """engine='duckduckgo' 이면 search 가 호출되고 type_text 가 수행된다 (enable_google=False 고정).

    기본값(스위치 OFF) 상태에서도 ddg/bing 은 정상 선택·실행된다.
    """
    # 기본값(enable_google=False) 에서 ddg 는 정상 동작한다.
    cfg = SearchConfig(engine="duckduckgo")
    humanizer = _make_mock_humanizer()
    page = _make_mock_page()

    dispatcher = SearchDispatcher(cfg, humanizer)
    # 캡차 탐지 경로를 타지 않도록 cdp_bridge 는 None(기본).
    with mock.patch("core.search.time.sleep"):
        result = dispatcher.run(page, "weather today")

    # 반환이 문자열(정상 결과 요약)이고, 검색창(오타 포함) 타이핑이 호출되었다.
    assert isinstance(result, str)
    humanizer.type_text_with_typos.assert_called_once()


def test_dispatcher_google_disabled_raises() -> None:
    """enable_google=False + engine='google' 이면 _select_engine 이 ValueError 를 던진다.

    (RED→GREEN) 기본값(스위치 OFF) 상태에서 google 엔진 선택이 차단되어야 한다.
    """
    # enable_google 은 기본 False — google 은 비활성.
    cfg = SearchConfig(engine="google")
    assert cfg.enable_google is False
    dispatcher = SearchDispatcher(cfg)
    with pytest.raises(ValueError):
        dispatcher._select_engine()


def test_dispatcher_google_enabled_selects() -> None:
    """enable_google=True + engine='google' 이면 _select_engine 이 GoogleSearch 를 반환 (GREEN).

    실제 검색(run) 은 수행하지 않고 선택 로직만 검증 — 네트워크/실제 구글 호출 없음(Mock).
    """
    cfg = SearchConfig(engine="google", enable_google=True)
    assert cfg.enable_google is True
    dispatcher = SearchDispatcher(cfg)
    engine = dispatcher._select_engine()
    # 활성화 스위치 ON 이면 GoogleSearch 인스턴스가 선택된다.
    assert isinstance(engine, GoogleSearch)


def test_dispatcher_captcha_returns_hitl() -> None:
    """캡차 흔적 탐지 시 run() 이 HITLRequest 를 반환한다 (cdp_bridge 재사용)."""
    cfg = SearchConfig(engine="duckduckgo")
    humanizer = _make_mock_humanizer()
    page = _make_mock_page()

    # cdp_bridge.detect_and_request_hitl() 이 HITLRequest 를 돌려주도록 모킹.
    fake_cdp = mock.MagicMock()
    fake_cdp.detect_and_request_hitl.return_value = HITLRequest(
        url="https://duckduckgo.com/captcha", reason="captcha_detected"
    )

    dispatcher = SearchDispatcher(cfg, humanizer, cdp_bridge=fake_cdp)
    with mock.patch("core.search.time.sleep"):
        result = dispatcher.run(page, "blocked query")

    # 캡차 시 HITLRequest 가 그대로 반환되어야 한다.
    assert isinstance(result, HITLRequest)
    assert result.reason == "captcha_detected"
    # cdp_bridge 의 캡차 탐지가 실제로 호출되었는지 확인.
    fake_cdp.detect_and_request_hitl.assert_called_once()


def test_engine_weights_applied() -> None:
    """google 의 _wait_results 가 ddg 보다 길다 (wait_x 배율 적용 검증).

    ``random.uniform`` 을 고정값(2.0)으로 패치 → base 가 동일할 때
    google(wait_x=1.5) 의 sleep 이 ddg(wait_x=1.0) 보다 커야 한다.
    """
    # google 엔진: wait_x = 1.5.
    google_cfg = SearchConfig(engine="google")
    google_engine = GoogleSearch(google_cfg)
    with mock.patch("core.search.time.sleep") as sleep_g, mock.patch(
        "core.search.random.uniform", return_value=2.0
    ):
        google_engine._wait_results()
    google_sleep = sleep_g.call_args[0][0]

    # duckduckgo 엔진: wait_x = 1.0.
    ddg_cfg = SearchConfig(engine="duckduckgo")
    ddg_engine = DuckDuckGoSearch(ddg_cfg)
    with mock.patch("core.search.time.sleep") as sleep_d, mock.patch(
        "core.search.random.uniform", return_value=2.0
    ):
        ddg_engine._wait_results()
    ddg_sleep = sleep_d.call_args[0][0]

    # bing 엔진: wait_x = 1.2 (google > bing > ddg 순으로 길어야 함).
    bing_cfg = SearchConfig(engine="bing")
    bing_engine = BingSearch(bing_cfg)
    with mock.patch("core.search.time.sleep") as sleep_b, mock.patch(
        "core.search.random.uniform", return_value=2.0
    ):
        bing_engine._wait_results()
    bing_sleep = sleep_b.call_args[0][0]

    # google 이 ddg/bing 보다 더 길게 대기한다 (엔진별 wait_x 배율).
    assert google_sleep > bing_sleep > ddg_sleep
    # 배율이 정확히 적용되었는지 확인 (base=2.0 * wait_x).
    assert abs(google_sleep - 2.0 * 1.5) < 1e-9
    assert abs(bing_sleep - 2.0 * 1.2) < 1e-9
    assert abs(ddg_sleep - 2.0 * 1.0) < 1e-9


def test_dispatcher_session_gap_called() -> None:
    """dispatcher.run() 호출 시 humanizer.session_gap() 이 실행된다.

    연속 검색 세션 패턴 완화를 위해 검색 전 session_gap() 이 호출되는지,
    그리고 검색 후 vary_query() 도 호출되는지(MagicMock humanizer 로 검증) 확인.
    """
    cfg = SearchConfig(engine="duckduckgo")
    humanizer = _make_mock_humanizer()
    page = _make_mock_page()

    dispatcher = SearchDispatcher(cfg, humanizer)
    # 캡차 탐지 경로를 타지 않도록 cdp_bridge 는 None(기본).
    with mock.patch("core.search.time.sleep"):
        dispatcher.run(page, "test query")

    # 검색 전 세션 간격 대기가 호출되었다.
    humanizer.session_gap.assert_called_once()
    # 검색 후 다음 쿼리 변형 준비(vary_query)도 호출되었다.
    humanizer.vary_query.assert_called_once_with("test query")


def test_summarize_parses_links() -> None:
    """_summarize 는 page.evaluate 로 추출한 링크(N개)와 제목을 포함한다.

    MagicMock ``page.evaluate`` 가 링크 리스트를 반환하면, 요약 문자열에
    ``results=N`` 과 각 링크 제목/URL 이 포함되는지 검증한다.
    """
    cfg = SearchConfig(engine="duckduckgo")
    engine = DuckDuckGoSearch(cfg)
    page = _make_mock_page()
    # page.evaluate 가 링크 리스트를 반환하도록 모킹.
    page.evaluate.return_value = [
        {"title": "Result One", "url": "https://a.example.com"},
        {"title": "Result Two", "url": "https://b.example.com"},
    ]

    summary = engine._summarize(page, "test query")

    # page.evaluate 가 실제로 호출되었는지(링크 추출 경로).
    page.evaluate.assert_called_once()
    # results=N (N=2) 와 각 링크 제목/URL 포함 확인.
    assert "results=2" in summary
    assert "Result One" in summary
    assert "Result Two" in summary
    assert "https://a.example.com" in summary
    assert "https://b.example.com" in summary


def test_search_clicks_depth() -> None:
    """search() 는 pick_click_depth() 를 호출하고 depth>0 이면 page.goto 를 수행한다.

    링크가 존재하는 상황에서 ``humanizer.pick_click_depth()`` 가 호출되고,
    depth>0 이면 결과 URL 로 ``page.goto``(클릭 시뮬) 가 호출되는지 검증한다.
    """
    cfg = SearchConfig(engine="duckduckgo")
    humanizer = _make_mock_humanizer()
    page = _make_mock_page()
    # 링크가 존재하도록 evaluate 모킹 + 클릭 깊이 2 로 강제.
    page.evaluate.return_value = [
        {"title": "A", "url": "https://a.example.com"},
        {"title": "B", "url": "https://b.example.com"},
        {"title": "C", "url": "https://c.example.com"},
    ]
    humanizer.pick_click_depth.return_value = 2

    engine = DuckDuckGoSearch(cfg)
    with mock.patch("core.search.time.sleep"):
        # search() 는 (summary, meta) 튜플 반환 — summary 는 result[0].
        result = engine.search(page, humanizer, "click test")

    # pick_click_depth() 가 호출되었는지.
    humanizer.pick_click_depth.assert_called_once()
    # depth(2) > 0 이므로 인간적 행동(새 탭 열기 + hover) 이 수행되어야 함.
    # depth 중 1개는 새 탭에서 열었다 닫는 시뮬(page.context.new_page 호출).
    assert page.context.new_page.called
    # 나머지는 hover 만 수행(page.hover 호출).
    page.hover.assert_called()
    # 결과 요약 문자열이 result[0] 에 반환된다 (링크 3개).
    assert isinstance(result, tuple)
    summary = result[0]
    assert isinstance(summary, str)
    assert "results=3" in summary
    # Bug B 보강: 새 탭(이동한 개별 사이트)에서도 humanizer 가 적용되는지.
    # _post_search 에서 메인 페이지 스크롤(scrolls=4) 외에, 새 탭 열기 경로에서도
    # scroll_to_bottom(scrolls=2) 가 호출되어야 한다. 새 탭 mock 을 식별해 확인.
    new_tab = page.context.new_page.return_value
    scroll_calls_new_tab = [
        c
        for c in humanizer.scroll_to_bottom.call_args_list
        if len(c.args) >= 1 and c.args[0] is new_tab
    ]
    assert scroll_calls_new_tab  # 새 탭에서 humanizer(스크롤) 적용됨


def test_apply_click_depth_applies_humanizer_on_new_tab() -> None:
    """_apply_click_depth 는 새 탭(이동한 개별 사이트)에서도 humanizer 를 적용한다 (Bug B).

    결과 페이지뿐 아니라 새 탭으로 연 개별 사이트에서도
    ``scroll_to_bottom`` / ``think_pause`` / ``move_mouse_bezier`` 가 호출되어야
    함(Cloudflare 등 개별 사이트 봇 탐지 대비). ``page.context.new_page()`` 가
    반환한 새 탭 mock 에 대해 ``humanizer.scroll_to_bottom(new_tab, ...)`` 가
    호출되는지 검증한다.
    """
    cfg = SearchConfig(engine="duckduckgo")
    humanizer = _make_mock_humanizer()
    page = _make_mock_page()
    # 새 탭 mock (page.context.new_page 가 반환).
    new_tab = mock.MagicMock()
    page.context.new_page.return_value = new_tab
    # 링크 1개 + 클릭 깊이 1 → 정확히 새 탭 1개 열림.
    links = [{"title": "A", "url": "https://a.example.com"}]
    humanizer.pick_click_depth.return_value = 1

    engine = DuckDuckGoSearch(cfg)
    with mock.patch("core.search.time.sleep"):
        engine._apply_click_depth(page, humanizer, links)

    # 새 탭이 열렸는지.
    page.context.new_page.assert_called_once()
    # 새 탭에서 humanizer 가 적용되었는지 (스크롤/체류/마우스).
    humanizer.scroll_to_bottom.assert_called_once()
    # 첫 인자가 새 탭 mock 인지 (개별 사이트에서 적용됨을 보장).
    assert humanizer.scroll_to_bottom.call_args[0][0] is new_tab
    humanizer.think_pause.assert_called()
    humanizer.move_mouse_bezier.assert_called()
    # 새 탭이 닫혔는지.
    new_tab.close.assert_called_once()


def test_dynamic_weights_no_dup(tmp_path) -> None:
    """중복쿼리가 없으면(빈 로그) _compute_dynamic_weights 가 기본값과 동일(factor=1.0).

    실제 SessionLog(tmp_path) 에 항목을 주입하지 않으면 duplicate_query_ratio 가
    0.0 을 반환하고, 보정 factor 도 1.0 이 되어 engine_weights 가 변하지 않는다.
    """
    cfg = SearchConfig(engine="duckduckgo")
    dispatcher = SearchDispatcher(cfg)
    # 빈 실제 세션 로그 주입 — 중복 비율 0.0 (MagicMock 이 아닌 실제 파일 기반).
    dispatcher.session_log = SessionLog(str(tmp_path / "empty.jsonl"))

    dynamic = dispatcher._compute_dynamic_weights()

    # 모든 엔진 배율이 기본값과 일치해야 함 (factor=1.0, 상한 미도달).
    assert dynamic == cfg.engine_weights


def test_dynamic_weights_high_dup(tmp_path) -> None:
    """중복쿼리 10건 주입 시 google.wait_x 가 기본(1.5) 초과·상한(2.0) 이하.

    동일 쿼리 10건을 실제 SessionLog 에 기록하면 duplicate_query_ratio=1.0 이고,
    factor = 1.0 + min(1.0, 0.5)*0.6 = 1.3 이 된다. google wait_x(기본 1.5) 보정값은
    1.5 * 1.3 = 1.95 로, 1.5 초과이자 2.0 이하임을 검증한다.
    """
    cfg = SearchConfig(engine="duckduckgo")
    dispatcher = SearchDispatcher(cfg)
    # 실제 세션 로그에 동일 쿼리 10건 주입.
    log = SessionLog(str(tmp_path / "dup.jsonl"))
    for _ in range(10):
        log.append(SearchLogEntry(engine="duckduckgo", query="same query", results_count=3))
    dispatcher.session_log = log

    dynamic = dispatcher._compute_dynamic_weights()

    # 중복 비율이 높으면 보정 factor 가 1.0 초과 (값이 커졌음).
    assert dynamic["google"]["wait_x"] > cfg.engine_weights["google"]["wait_x"]
    # google wait_x 기본 1.5 → 보정 1.95 (1.5 초과, 2.0 이하 상한).
    assert dynamic["google"]["wait_x"] > 1.5
    assert dynamic["google"]["wait_x"] <= 2.0
    # 상한 2.0 엄수 — 임의 엔진의 어떤 배율도 2.0 초과 불가.
    for _engine, weights in dynamic.items():
        for value in weights.values():
            assert value <= 2.0


def test_extract_links_engine_selector() -> None:
    """엔진별 정밀 셀렉터가 page.evaluate 인자로 전달된다 (Google=div.g a).

    ``_extract_links`` 는 ``self._RESULT_SELECTOR`` 를 JS 두 번째 인자로 넘기며,
    각 엔진(Google/DDG/Bing)이 서로 다른 정밀 셀렉터를 정의해야 한다.
    """
    engine = GoogleSearch(SearchConfig(engine="google"))
    page = _make_mock_page()
    page.evaluate.return_value = [{"title": "G Result", "url": "https://g.example.com"}]

    links = engine._extract_links(page)

    # 정밀 셀렉터 경로가 1회 호출로 결과를 반환한다 (fallback 재시도 없음).
    assert links == [{"title": "G Result", "url": "https://g.example.com"}]
    page.evaluate.assert_called_once()
    call_args = page.evaluate.call_args[0]
    # (js, selector) 2-인자 호출이며 selector 에 google 정밀 셀렉터가 포함된다.
    assert len(call_args) == 2
    assert "div.g a" in call_args[1]
    assert call_args[1] == GoogleSearch._RESULT_SELECTOR
    # 엔진별로 셀렉터가 구분되어 정의되어 있다 (DDG/Bing).
    assert "result-title-a" in DuckDuckGoSearch._RESULT_SELECTOR
    assert "b_algo" in BingSearch._RESULT_SELECTOR


def test_extract_links_fallback_when_empty_selector() -> None:
    """_RESULT_SELECTOR 가 빈 문자열이면 범용 fallback(a[href] 필터) 경로를 쓴다.

    또한 정밀 셀렉터가 0건을 반환하면 빈 셀렉터로 자동 재시도(fallback)한다.
    """

    class _PlainEngine(SearchEngine):
        """셀렉터 미정의 상태(_RESULT_SELECTOR="")를 검증하기 위한 스텁 엔진."""

        engine_name = "plain"
        base_url = "https://plain.example.com/search"

        def search(self, page: object, humanizer: object, query: str) -> tuple[str, dict]:
            """추상 메서드 충족용 최소 구현 (본 테스트에서는 미사용)."""
            return self._summarize(page, query), {}

    # 1) 빈 셀렉터 → fallback 경로 (selector 인자가 빈 문자열).
    assert _PlainEngine._RESULT_SELECTOR == ""
    engine = _PlainEngine(SearchConfig())
    page = _make_mock_page()
    page.evaluate.return_value = [{"title": "Fallback", "url": "https://f.example.com"}]

    links = engine._extract_links(page)

    assert links == [{"title": "Fallback", "url": "https://f.example.com"}]
    page.evaluate.assert_called_once()
    js_src, selector = page.evaluate.call_args[0]
    # 빈 셀렉터가 전달되고, JS 에 범용 fallback 필터(a[href])가 존재한다.
    assert selector == ""
    assert "a[href]" in js_src

    # 2) 정밀 셀렉터가 0건이면 빈 셀렉터로 자동 재시도한다 (evaluate 2회).
    google_page = _make_mock_page()
    google_page.evaluate.side_effect = [
        [],
        [{"title": "Retried", "url": "https://r.example.com"}],
    ]
    google_links = GoogleSearch(SearchConfig(engine="google"))._extract_links(google_page)

    assert google_links == [{"title": "Retried", "url": "https://r.example.com"}]
    assert google_page.evaluate.call_count == 2
    # 재시도 호출은 fallback(빈 셀렉터)으로 이루어진다.
    assert google_page.evaluate.call_args_list[1][0][1] == ""
