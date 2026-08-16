"""인간 행동 모방 엔진 테스트 (tests/unit/test_humanizer.py).

검증 대상(src/core/humanizer.py):
    - ``HumanizerConfig`` (pydantic v2) 기본값 8+ 필드 명세.
    - ``Humanizer`` 의 5개 동작 메서드:
        * type_text: 한 글자씩 keyboard.type 호출 + 문자 간 sleep.
        * move_mouse_bezier: mouse_steps 회 이상 mouse.move 호출.
        * think_pause: pause_min~max 범위 내 sleep.
        * random_scroll: scroll_prob=1.0 일 때 wheel 호출, 0.0 일 때 미호출.
        * _bezier_point: 순수 함수 보간.

실제 Chrome 기동 금지. ``page`` 는 MagicMock 으로 대체하고
``time.sleep`` / ``random`` 을 패치하여 동작 횟수·범위를 검증한다.

컨벤션: snake_case, 한국어 주석. pytest + unittest.mock.
"""

from __future__ import annotations

import random
from unittest import mock

import pytest

from core.humanizer import Humanizer, HumanizerConfig


def _make_mock_page() -> mock.MagicMock:
    """page.click / keyboard.type / mouse.move / mouse.wheel 을 가진 mock page."""
    page = mock.MagicMock()
    # mouse.move, mouse.wheel, keyboard.type, click 모두 호출 기록을 남긴다.
    page.mouse.move = mock.MagicMock()
    page.mouse.wheel = mock.MagicMock()
    page.keyboard.type = mock.MagicMock()
    page.click = mock.MagicMock()
    return page


def test_config_defaults() -> None:
    """HumanizerConfig 기본값이 명세와 일치한다 (8+ 필드)."""
    cfg = HumanizerConfig()

    # 키 입력 지연 (ms).
    assert cfg.typing_min_ms == 40
    assert cfg.typing_max_ms == 180
    # 마우스 궤적.
    assert cfg.mouse_steps == 24
    assert cfg.mouse_jitter_px == 3.0
    # 생각 대기 (s).
    assert cfg.pause_min_s == 0.3
    assert cfg.pause_max_s == 2.5
    # 스크롤 확률.
    assert cfg.scroll_prob == 0.4
    # 필드 포커스 후 지연 (s).
    assert cfg.field_delay_min_s == 0.2
    assert cfg.field_delay_max_s == 0.8

    # min <= max 불변식도 함께 보장.
    assert cfg.typing_min_ms <= cfg.typing_max_ms
    assert cfg.pause_min_s <= cfg.pause_max_s
    assert cfg.field_delay_min_s <= cfg.field_delay_max_s


def test_bezier_point_endpoints() -> None:
    """_bezier_point 는 t=0 에서 시작점, t=1 에서 끝점을 반환한다 (순수 함수)."""
    p0 = (0.0, 0.0)
    p1 = (5.0, 10.0)
    p2 = (10.0, 0.0)

    assert Humanizer._bezier_point(0.0, p0, p1, p2) == (0.0, 0.0)
    assert Humanizer._bezier_point(1.0, p0, p1, p2) == (10.0, 0.0)


def test_type_text_types_char_by_char() -> None:
    """type_text 는 텍스트 길이만큼 keyboard.type 을 호출하고 문자 간 sleep 한다."""
    page = _make_mock_page()
    humanizer = Humanizer()

    text = "hello"
    # sleep 을 패치하여 시간 소모 없이 호출 횟수만 기록한다.
    with mock.patch("core.humanizer.time.sleep") as fake_sleep:
        humanizer.type_text(page, "input#q", text)

    # 1) selector 클릭(포커스) 1회.
    page.click.assert_called_once_with("input#q")

    # 2) 각 문자마다 keyboard.type 1회 → 길이만큼.
    assert page.keyboard.type.call_count == len(text)
    typed_chars = [c.args[0] for c in page.keyboard.type.call_args_list]
    assert typed_chars == ["h", "e", "l", "l", "o"]

    # 3) 문자 간 sleep 은 (필드 지연 1회 + 문자 수만큼) 발생해야 한다.
    #    필드 지연 1회 + 글자 5개 = 최소 6회.
    assert fake_sleep.call_count >= len(text) + 1


def test_type_text_clears_existing() -> None:
    """type_text 는 기존 입력을 fill(selector, "") 로 강제 클리어한다.

    검색창에 이전 쿼리가 남아있으면 새 쿼리가 덧붙여지는 버그(Bing SPA 등)를
    막기 위해, ``page.click`` 으로 포커스한 직후 ``page.fill(selector, "")`` 가
    호출되어 기존 내용을 무조건 덮어쓰기로 지우는지 MagicMock 으로 검증한다
    (SPA 자체 value 관리와 무관하게 동작).
    """
    page = _make_mock_page()
    humanizer = Humanizer()

    # sleep 을 패치하여 시간 소모 없이 fill 호출만 기록한다.
    with mock.patch("core.humanizer.time.sleep"):
        humanizer.type_text(page, "#s", "hello")

    # 1) selector 클릭(포커스) 1회.
    page.click.assert_called_once_with("#s")
    # 2) 기존 내용 강제 클리어를 위한 fill(selector, "") 호출 검증.
    page.fill.assert_called_with("#s", "")


def test_move_mouse_bezier_steps() -> None:
    """move_mouse_bezier 는 mouse_steps 회 이상 mouse.move 를 호출한다."""
    page = _make_mock_page()
    humanizer = Humanizer()
    steps = humanizer.config.mouse_steps

    with mock.patch("core.humanizer.time.sleep"), mock.patch(
        "core.humanizer.random"
    ) as fake_random:
        # gauss/move 지터에서 쓰는 random 호출을 결정적으로 만든다.
        fake_random.gauss.return_value = 0.0
        fake_random.uniform.return_value = 0.0
        humanizer.move_mouse_bezier(page, 0, 0, 100, 100)

    # 분할 단계(steps+1) 이상 move 가 호출된다.
    assert page.mouse.move.call_count >= steps


def test_think_pause_delays() -> None:
    """think_pause 는 pause_min~max 범위 내의 값으로 sleep 한다."""
    humanizer = Humanizer()
    cfg = humanizer.config

    with mock.patch("core.humanizer.time.sleep") as fake_sleep, mock.patch(
        "core.humanizer.random.uniform", return_value=1.0
    ) as fake_uniform:
        humanizer.think_pause()

    # random.uniform(pause_min_s, pause_max_s) 형태로 호출되었는지 확인.
    fake_uniform.assert_called_once_with(cfg.pause_min_s, cfg.pause_max_s)
    # sleep 에 전달된 값이 반환값(1.0 → 범위 내)과 같아야 한다.
    fake_sleep.assert_called_once_with(1.0)
    # 범위 내 포함 보장.
    assert cfg.pause_min_s <= 1.0 <= cfg.pause_max_s


def test_random_scroll_probabilistic() -> None:
    """random_scroll 는 scroll_prob=1.0 이면 wheel 호출, 0.0 이면 미호출."""
    # 케이스 1: 확률 1.0 → 무조건 스크롤.
    page_on = _make_mock_page()
    humanizer_on = Humanizer(HumanizerConfig(scroll_prob=1.0))
    with mock.patch("core.humanizer.time.sleep"), mock.patch(
        "core.humanizer.random.random", return_value=0.5
    ), mock.patch("core.humanizer.random.randint", return_value=200):
        humanizer_on.random_scroll(page_on)
    page_on.mouse.wheel.assert_called_once()

    # 케이스 2: 확률 0.0 → 스크롤 안 함.
    page_off = _make_mock_page()
    humanizer_off = Humanizer(HumanizerConfig(scroll_prob=0.0))
    with mock.patch("core.humanizer.time.sleep"), mock.patch(
        "core.humanizer.random.random", return_value=0.5
    ):
        humanizer_off.random_scroll(page_off)
    page_off.mouse.wheel.assert_not_called()


def test_session_gap_delays() -> None:
    """session_gap 는 session_gap_min~max 범위 내의 값으로 sleep 한다."""
    humanizer = Humanizer()
    cfg = humanizer.config

    with mock.patch("core.humanizer.time.sleep") as fake_sleep, mock.patch(
        "core.humanizer.random.uniform", return_value=cfg.session_gap_min_s
    ) as fake_uniform:
        humanizer.session_gap()

    # random.uniform(session_gap_min_s, session_gap_max_s) 형태로 호출.
    fake_uniform.assert_called_once_with(cfg.session_gap_min_s, cfg.session_gap_max_s)
    # sleep 에 전달된 값이 반환값과 같아야 한다.
    fake_sleep.assert_called_once_with(cfg.session_gap_min_s)
    # 범위 내 포함 보장.
    assert cfg.session_gap_min_s <= cfg.session_gap_min_s <= cfg.session_gap_max_s


def test_pick_click_depth_range() -> None:
    """pick_click_depth 는 [click_depth_min, click_depth_max] 범위를 반환한다."""
    humanizer = Humanizer()
    cfg = humanizer.config

    # 범위 내 여러 후보값으로 randint 를 강제 호출해 반환값 검증.
    candidates = [cfg.click_depth_min, cfg.click_depth_max, 2, 3]
    with mock.patch(
        "core.humanizer.random.randint", side_effect=candidates
    ) as fake_randint:
        for expected in candidates:
            result = humanizer.pick_click_depth()
            assert cfg.click_depth_min <= result <= cfg.click_depth_max
            assert result == expected

    # randint 가 (click_depth_min, click_depth_max) 범위로 호출되었는지 확인.
    for call in fake_randint.call_args_list:
        assert call.args == (cfg.click_depth_min, cfg.click_depth_max)


def test_vary_query_no_meaning_change() -> None:
    """vary_query 는 핵심 토큰을 보존하고, prob=0 이면 원본을 반환한다."""
    original = "Qwen3.8 오픈 웨이트"

    # 케이스 1: query_variant_prob=0 이면 항상 원본과 동일 반환.
    humanizer_zero = Humanizer(HumanizerConfig(query_variant_prob=0.0))
    assert humanizer_zero.vary_query(original) == original

    # 케이스 2: 변형 경로 강제(random.random=0.1 < 0.3)해도 핵심 토큰 보존.
    humanizer = Humanizer()  # 기본 prob=0.3
    with mock.patch("core.humanizer.random.random", return_value=0.1):
        result = humanizer.vary_query(original)

    # 핵심 토큰("Qwen3.8" 또는 "오픈") 중 최소 하나 포함 유지.
    assert "Qwen3.8" in result or "오픈" in result


def test_type_text_with_typos_calls_backspace() -> None:
    """type_text_with_typos 는 typo_prob=1.0 이면 매 문자마다 Backspace 를 호출한다.

    오타·수정 흉내 경로(잘못 입력 → Backspace → 재입력)가 실제로 동작하는지,
    ``page.keyboard.press`` 가 문자당 1회 호출되고 인자에 ``"Backspace"`` 가
    포함되는지 MagicMock 으로 검증한다.
    """
    page = _make_mock_page()
    humanizer = Humanizer()
    text = "hello"

    with mock.patch("core.humanizer.time.sleep"):
        # typo_prob=1.0 → 모든 문자에서 오타·수정 경로 강제.
        humanizer.type_text_with_typos(page, "input#q", text, typo_prob=1.0)

    # 1) selector 클릭(포커스) 1회.
    page.click.assert_called_once_with("input#q")
    # 2) 올바른 문자도 정상 입력되었는지(길이만큼 이상).
    typed = [c.args[0] for c in page.keyboard.type.call_args_list]
    assert "h" in typed and "e" in typed
    # 3) typo_prob=1.0 → 모든 문자에서 Backspace 호출 (문자당 1회).
    #    클리어는 이제 fill(selector, "") 로 처리되므로 Backspace 는 오타·수정
    #    경로만큼(len(text))만 발생한다.
    press_calls = [c.args[0] for c in page.keyboard.press.call_args_list]
    assert press_calls.count("Backspace") == len(text)
    assert "Backspace" in press_calls


def test_scroll_to_bottom_calls_wheel() -> None:
    """scroll_to_bottom(page, scrolls=3) 는 page.mouse.wheel 을 3회 호출한다.

    확률 변수 없이 입력 횟수만큼 확정적으로 아래로 스크롤하는지 검증한다.
    """
    page = _make_mock_page()
    humanizer = Humanizer()

    with mock.patch("core.humanizer.time.sleep"), mock.patch(
        "core.humanizer.random.randint", return_value=400
    ):
        humanizer.scroll_to_bottom(page, scrolls=3)

    # 입력한 scrolls 회수만큼 wheel 호출.
    assert page.mouse.wheel.call_count == 3
    # 각 호출이 아래 방향(delta>0)으로 스크롤했는지 확인.
    for call in page.mouse.wheel.call_args_list:
        assert call.args[0] == 0  # x delta (없음)
        assert call.args[1] > 0  # y delta (아래로)


def _make_typing_buffer_page() -> tuple[mock.MagicMock, list[str]]:
    """타이핑 결과를 추적하는 mock page.

    ``keyboard.type(text)`` 는 문자를 버퍼에 추가, ``keyboard.press("Backspace")`` 는
    마지막 문자를 제거한다. 최종 버퍼를 join 하면 실제 입력창에 들어간 문자열과 같다.
    """

    buffer: list[str] = []
    page = mock.MagicMock()

    def fake_type(text: str) -> None:
        for ch in text:
            buffer.append(ch)

    def fake_press(key: str) -> None:
        if key == "Backspace" and buffer:
            buffer.pop()

    page.keyboard.type.side_effect = fake_type
    page.keyboard.press.side_effect = fake_press
    return page, buffer


def _typed_result(text: str, typo_prob: float, force_typo: float | None = None) -> str:
    """type_text_with_typos 실행 후 최종 입력 문자열(버퍼 join)을 반환한다.

    ``force_typo`` 가 주어지면 ``random.random`` 을 강제하여 오타 발생 여부를
    결정적으로 제어한다 (0.0 → 항상 오타, 1.0 → 항상 정상). ``None`` 이면 실제 난수.
    """
    humanizer = Humanizer()
    page, buffer = _make_typing_buffer_page()

    patches: list[object] = [mock.patch("core.humanizer.time.sleep")]
    if force_typo is not None:
        patches.append(
            mock.patch("core.humanizer.random.random", return_value=force_typo)
        )
    for p in patches:
        p.start()  # type: ignore[union-attr]
    try:
        humanizer.type_text_with_typos(page, "input#q", text, typo_prob=typo_prob)
    finally:
        for p in patches:
            p.stop()  # type: ignore[union-attr]
    return "".join(buffer)


def test_type_text_with_typos_no_duplicate_when_typo_forced() -> None:
    """오타를 매 문자마다 강제해도 최종 입력 문자열은 원본과 일치(중복 없음).

    버그 재현/방지 핵심: 오타 보정 경로(wrong → Backspace → 재입력)가 원글자르
    다시 타입하면 해당 글자가 1개 중복된다. 본 테스트는 그 경로가 최종값을
    오염시키지 않음을 검증한다.
    """
    result = _typed_result("hello", typo_prob=0.15, force_typo=0.0)
    assert result == "hello"
    # 중복 없음 보조 검증: 버퍼 시퀀스가 원본과 동일.
    assert list(result) == list("hello")


def test_type_text_with_typos_no_duplicate_when_no_typo() -> None:
    """오타가 전혀 없을 때도 최종 입력 문자열은 원본과 일치한다."""
    result = _typed_result("hello", typo_prob=0.15, force_typo=1.0)
    assert result == "hello"


def test_type_text_with_typos_no_duplicate_random_stress() -> None:
    """typo_prob=0.15 실제 난수로 300회 반복 — 항상 최종값==원본(중복 없음).

    공백 포함 쿼리와 다중 단어 쿼리 모두에서 어떤 글자 조합의 오타가 들어가더라도
    최종 입력 문자열이 원본과 같아야 한다 (글자 중복 버그 회귀 방지).
    """
    random.seed(1234)
    for _ in range(300):
        result = _typed_result("test query", typo_prob=0.15)
        assert result == "test query", f"중복 발생: {result!r}"

    for _ in range(300):
        result = _typed_result("qwen 3.8 open weights", typo_prob=0.15)
        assert result == "qwen 3.8 open weights", f"중복 발생: {result!r}"


# --- move_mouse_to_element (M2: 링크 위치로 마우스 이동) ---


def _make_box(x: float = 100.0, y: float = 50.0, width: float = 80.0, height: float = 20.0) -> dict:
    """_get_element_box 가 반환하는 bounding box dict 스텁."""
    return {"x": x, "y": y, "width": width, "height": height}


def test_move_mouse_to_element_calls_bezier_with_center() -> None:
    """move_mouse_to_element 는 중심좌표(cx, cy)로 move_mouse_bezier 를 호출한다.

    page.evaluate 가 bounding box 를 반환하도록 stub 하고, move_mouse_bezier 를
    스파이(wraps)로 감싸 호출 인자를 단언한다. 시작점은 초기 화면 밖 (-10, -10),
    끝점은 중심좌표가 되어야 한다.
    """
    humanizer = Humanizer(HumanizerConfig(mouse_steps=3))  # 빠른 실행
    page = _make_mock_page()
    box = _make_box(x=100.0, y=50.0, width=80.0, height=20.0)
    page.evaluate.return_value = box
    expected_cx = 100.0 + 80.0 / 2.0  # 140.0
    expected_cy = 50.0 + 20.0 / 2.0  # 60.0

    with mock.patch("core.humanizer.time.sleep"), mock.patch.object(
        humanizer, "move_mouse_bezier", wraps=humanizer.move_mouse_bezier
    ) as spy:
        result = humanizer.move_mouse_to_element(page, "a.result")

    # 1) 반환값은 중심좌표.
    assert result == (expected_cx, expected_cy)
    # 2) page.evaluate 가 bounding box 획득에 한 번 호출되었는지.
    page.evaluate.assert_called_once()
    # 3) move_mouse_bezier 가 중심좌표(끝점)로 호출되었는지.
    assert spy.called
    args = spy.call_args
    # call_args: (page, x0, y0, x1, y1) — 끝점(x1,y1) == 중심.
    assert abs(args.args[1] - (-10.0)) < 1e-6  # 시작점 x = 초기 화면 밖
    assert abs(args.args[2] - (-10.0)) < 1e-6  # 시작점 y = 초기 화면 밖
    assert abs(args.args[3] - expected_cx) < 1e-6  # 끝점 x = 중심
    assert abs(args.args[4] - expected_cy) < 1e-6  # 끝점 y = 중심


def test_move_mouse_to_element_missing_selector_returns_none() -> None:
    """셀렉터 미존재(box=None) 시 move_mouse_bezier 미호출 + None 반환."""
    humanizer = Humanizer(HumanizerConfig(mouse_steps=1))
    page = _make_mock_page()
    page.evaluate.return_value = None  # 요소를 찾지 못함

    with mock.patch("core.humanizer.time.sleep"), mock.patch.object(
        humanizer, "move_mouse_bezier"
    ) as spy:
        result = humanizer.move_mouse_to_element(page, "a.missing")

    assert result is None
    spy.assert_not_called()


def test_move_mouse_to_element_tracks_cursor_between_moves() -> None:
    """연속 호출 시 커서 위치가 누적되어 다음 이동의 시작점이 된다.

    첫 이동으로 _mouse_pos 가 중심1 로 갱신되고, 두 번째 이동은 그 지점에서
    출발(start == 중심1)해야 한다.
    """
    humanizer = Humanizer(HumanizerConfig(mouse_steps=2))
    page = _make_mock_page()
    box1 = _make_box(x=100.0, y=50.0, width=80.0, height=20.0)  # center (140, 60)
    box2 = _make_box(x=300.0, y=200.0, width=40.0, height=40.0)  # center (320, 220)

    with mock.patch("core.humanizer.time.sleep"), mock.patch.object(
        humanizer, "move_mouse_bezier", wraps=humanizer.move_mouse_bezier
    ) as spy:
        page.evaluate.return_value = box1
        humanizer.move_mouse_to_element(page, "a.first")
        page.evaluate.return_value = box2
        humanizer.move_mouse_to_element(page, "a.second")

    assert spy.call_count == 2
    first_call = spy.call_args_list[0]
    second_call = spy.call_args_list[1]
    # 첫 이동: 시작점 화면 밖 (-10,-10) → 중심1 (140,60).
    assert (first_call.args[1], first_call.args[2]) == (-10.0, -10.0)
    assert (first_call.args[3], first_call.args[4]) == (140.0, 60.0)
    # 두 번째 이동: 시작점 = 직전 중심 (140,60) → 중심2 (320,220).
    assert (second_call.args[1], second_call.args[2]) == (140.0, 60.0)
    assert (second_call.args[3], second_call.args[4]) == (320.0, 220.0)


def test_move_mouse_to_element_clicks_when_requested() -> None:
    """click=True 시 중심 위치로 page.mouse.click 이 호출된다."""
    humanizer = Humanizer(HumanizerConfig(mouse_steps=2))
    page = _make_mock_page()
    box = _make_box(x=100.0, y=50.0, width=80.0, height=20.0)
    page.evaluate.return_value = box
    expected_cx = 140.0
    expected_cy = 60.0

    with mock.patch("core.humanizer.time.sleep"):
        result = humanizer.move_mouse_to_element(page, "a.result", click=True)

    assert result == (expected_cx, expected_cy)
    # page.mouse.click(cx, cy) 가 정확히 한 번 호출되었는지.
    page.mouse.click.assert_called_once_with(expected_cx, expected_cy)


def test_move_mouse_to_element_fail_on_missing_raises() -> None:
    """fail_on_missing=True 이며 요소가 없으면 ValueError 가 발생한다."""
    humanizer = Humanizer(HumanizerConfig(mouse_steps=1))
    page = _make_mock_page()
    page.evaluate.return_value = None

    with mock.patch("core.humanizer.time.sleep"), pytest.raises(ValueError):
        humanizer.move_mouse_to_element(page, "a.missing", fail_on_missing=True)

