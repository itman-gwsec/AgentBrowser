"""인간 행동 모방 엔진 (Human-like behavior engine).

실제(헤드풀) Chrome 은 UA/WebGL/지문이 이미 인간과 동일하므로, 남은 봇 탐지
회피 변수는 **동작 패턴**뿐이다. 이 모듈은 Playwright ``page`` 객체를 받아
다음 인간유사 동작을 수행한다:

- 키 입력: 한 글자씩, 균일하지 않은 리듬으로 (붙여넣기 아님)
- 마우스 이동: 2차 베지어 곡선 + 미세 가우시안 지터 (직선 이동 아님)
- 대기: 액션 사이의 무작위 '생각'暂停 (think pause)
- 스크롤: 확률적 스크롤

설계 제약 (IDEA.md / design doc §4):
- 익스텐션(JS) 회피 로직은 일절 포함하지 않는다. Python agent 레이어에서만 구현.
- ``time.sleep`` 을 제거하지 않는다 — 인간 리듬 그 자체가 목적이기 때문.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from pydantic import BaseModel, Field

# 모듈 전역 로거 (print 금지, 일관성 유지).
logger = logging.getLogger(__name__)

# 쿼리 변형 시 "최신 " 접두사를 부가할 확률 (0.0~1.0).
_QUERY_PREFIX_PROB: float = 0.5

# 오타 시뮬레이션용 후보 풀 (type_text_with_typos 전용).
# - 알파벳: QWERTY 배열 인접 키 위주 (인간 오타 분포 근사).
# - 한글: 자주 쓰는 음절 위주.
_TYPO_ALPHA: str = "qwertyasdfzxcv"
_TYPO_HANGUL: str = "가나다라마바사아자차카타파하"


class ElementNotFoundError(ValueError):
    """셀렉터에 해당하는 요소를 찾을 수 없을 때 발생한다 (ValueError 하위)."""


def _is_hangul(char: str) -> bool:
    """단일 문자가 현대 한국어 음절(U+AC00~U+D7A3)인지 판별한다."""
    return "가" <= char <= "힣"


class HumanizerConfig(BaseModel):
    """인간 행동 모방 엔진 설정 (pydantic v2).

    모든 딜레이/확률 값은 인간이 균일하지 않다는 사실을 반영한다.
    min < max 가 되도록 ``Field`` 제약을 건다.
    """

    # 키 입력 간 지연(밀리초) — 인간은 균일한 타자 리듬을 갖지 않음.
    typing_min_ms: int = Field(default=40, ge=0, description="키 입력 최소 지연(ms)")
    typing_max_ms: int = Field(default=180, ge=0, description="키 입력 최대 지연(ms)")

    # 마우스 궤적 분할 수 (단계 수).
    mouse_steps: int = Field(default=24, ge=1, description="베지어 궤적 분할 단계 수")

    # 궤적에 더하는 미세 가우시안 노이즈(픽셀) — 직선이 아닌 곡선을 만듦.
    mouse_jitter_px: float = Field(default=3.0, ge=0.0, description="마우스 궤적 지터(픽셀)")

    # 액션 간 '생각' 대기(초).
    pause_min_s: float = Field(default=0.3, ge=0.0, description="생각 대기 최소(초)")
    pause_max_s: float = Field(default=2.5, ge=0.0, description="생각 대기 최대(초)")

    # 확률적 스크롤 발생 확률 (0.0~1.0).
    scroll_prob: float = Field(default=0.4, ge=0.0, le=1.0, description="스크롤 발생 확률")

    # 필드 포커스 후 실제 타이핑 시작 전 지연(초).
    field_delay_min_s: float = Field(
        default=0.2, ge=0.0, description="필드 포커스 후 최소 지연(초)"
    )
    field_delay_max_s: float = Field(
        default=0.8, ge=0.0, description="필드 포커스 후 최대 지연(초)"
    )

    # 세션 간격(초) — 검색 세션을 나누는 무작위 대기 상한/하한.
    session_gap_min_s: float = Field(
        default=5.0, ge=0.0, description="세션 간격 최소(초)"
    )
    session_gap_max_s: float = Field(
        default=20.0, ge=0.0, description="세션 간격 최대(초)"
    )

    # 클릭 깊이(페이지 탐색 깊이) 범위 — 무작위 링크 클릭 깊이 상한/하한.
    click_depth_min: int = Field(default=1, ge=0, description="클릭 깊이 최소")
    click_depth_max: int = Field(default=4, ge=0, description="클릭 깊이 최대")

    # 쿼리 변형 확률(0.0~1.0) — 검색어를 무해하게 변형할 확률.
    query_variant_prob: float = Field(
        default=0.3, ge=0.0, le=1.0, description="쿼리 변형 확률"
    )

    # 모델 직렬화/복사 시 추가 필드 거부 없이 동작하도록 설정.
    model_config = {"extra": "forbid"}


class Humanizer:
    """범용 인간유사 동작 엔진.

    Playwright ``page`` 객체를 메서드 인자로 받아 동작한다. ``cdp_bridge`` 가
    이미 Playwright 기반(page.keyboard / page.mouse / page.evaluate 사용)이므로
    호환된다. ``config`` 가 ``None`` 이면 기본값 설정으로 동작한다.
    """

    def __init__(self, config: HumanizerConfig | None = None) -> None:
        """설정을 보관한다. None 이면 기본값 인스턴스를 생성한다.

        Args:
            config: 인간 행동 모방 설정. 미지정 시 ``HumanizerConfig()`` 기본값.
        """
        self.config: HumanizerConfig = config if config is not None else HumanizerConfig()
        # 추적 중인 현재 커서 위치. 초기값은 화면 밖(아직 이동하지 않은 상태)으로 둔다.
        # ``move_mouse_to_element`` 가 이 값을 시작점으로 삼아 화면 밖→요소 중심
        # 곡선 이동을 만들고, 이후 누적된 위치를 다음 이동의 시작점으로 재사용한다.
        self._mouse_pos: tuple[float, float] = (-10.0, -10.0)
        logger.debug("Humanizer 초기화 (config=%s)", self.config.model_dump())

    @staticmethod
    def _bezier_point(
        t: float,
        p0: tuple[float, float],
        p1: tuple[float, float],
        p2: tuple[float, float],
    ) -> tuple[float, float]:
        """2차 베지어 곡선 위의 점을 반환하는 순수 함수.

        0 <= t <= 1 에 대해 ``(1-t)^2 * P0 + 2(1-t)t * P1 + t^2 * P2`` 를 계산한다.

        Args:
            t: 매개변수 (0.0=시작점, 1.0=끝점).
            p0: 시작점 (x, y).
            p1: 제어점 (x, y).
            p2: 끝점 (x, y).

        Returns:
            보간된 좌표 (x, y).
        """
        u = 1.0 - t
        x = u * u * p0[0] + 2.0 * u * t * p1[0] + t * t * p2[0]
        y = u * u * p0[1] + 2.0 * u * t * p1[1] + t * t * p2[1]
        return (x, y)

    def _make_control_point(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> tuple[float, float]:
        """시작점/끝점에서 수직 방향으로 오프셋된 제어점을 생성한다.

        직선이 아닌 곡선 궤적을 만들기 위해, 중점에서 수직 방향으로
        거리를 무작위로 밀어낸다. 오프셋 크기는 두 점 거리의 일부분을 따른다.

        Args:
            x0, y0: 시작점 좌표.
            x1, y1: 끝점 좌표.

        Returns:
            제어점 좌표 (x, y).
        """
        mid_x = (x0 + x1) / 2.0
        mid_y = (y0 + y1) / 2.0
        dx = x1 - x0
        dy = y1 - y0
        dist = (dx * dx + dy * dy) ** 0.5
        # 거리의 ~20% 만큼 수직 방향으로 무작위 밀어내기 (곡선 굽힘량).
        offset = dist * 0.2 * random.uniform(-1.0, 1.0)
        # 수직 단위 벡터 (-dy, dx) 정규화.
        if dist == 0.0:
            return (mid_x, mid_y)
        perp_x = -dy / dist
        perp_y = dx / dist
        return (mid_x + perp_x * offset, mid_y + perp_y * offset)

    def _clear_field(self, page: Any, selector: str) -> None:
        """검색창 잔존 텍스트 강제 클리어 (인간 행동: 기존 내용 지우고 입력).

        Playwright ``page.fill(selector, "")`` 는 입력 요소의 기존 내용을
        무조건 **덮어쓰기로 지운다**. 따라서 Bing/SPA 검색창처럼 value 를
        자체 관리하여 ``Control+a``/``Backspace``(select-all) 가 의도대로
        안 먹어 중복 입력 버그를 유발하던 기존 방식 대신, 가장 확실한
        fill 강제 초기화를 사용한다. fill 실패(셀렉터 미존재 등) 시 debug
        로그만 남기고 타자를 계속한다 (타자에 영향 없음).
        """
        try:
            # SPA 검색창도 강제로 비우는 가장 확실한 방식 (기존 내용 무조건 덮어쓰기).
            page.fill(selector, "")
            time.sleep(random.uniform(0.05, 0.2))  # 짧은 간격
        except Exception:  # fill 실패해도 타자에는 영향 없음
            logger.debug("필드 클리어 실패 (빈 칸 등) — 타자 계속 진행", exc_info=True)

    def type_text(
        self,
        page: Any,
        selector: str,
        text: str,
        typing_x: float = 1.0,
        pause_x: float = 1.0,
    ) -> None:
        """텍스트를 한 글자씩 인간 리듬으로 입력한다.

        ``selector`` 를 클릭(포커스) → 필드 지연 → 각 문자를
        ``page.keyboard.type(char)`` 로 입력하되, 문자 사이에 무작위
        지연(``typing_min_ms~typing_max_ms``)을 둔다. 인간은 붙여넣기하지 않고
        한 글자씩 치며 리듬이 있다.

        ``typing_x`` / ``pause_x`` 는 검색 엔진별 배율(기본 1.0)로,
        타자 지연과 포커스 후 '생각' 일시정지 범위를 각각 승수로 보정한다
        (1.0 이면 기존 동작과 동일).

        Args:
            page: Playwright page 객체 (런타임 타입 Any).
            selector: 입력 대상 요소 셀렉터.
            text: 입력할 문자열.
            typing_x: 타자 지연 승수 (기본 1.0).
            pause_x: 필드 포커스 후 지연 범위 승수 (기본 1.0).
        """
        page.click(selector)
        # 검색창 잔존 텍스트 강제 클리어 (fill 방식 — SPA 중복 입력 방지).
        self._clear_field(page, selector)
        logger.debug("필드 포커스 후 지연 적용 (selector=%s, pause_x=%.2f)", selector, pause_x)
        time.sleep(
            random.uniform(
                self.config.field_delay_min_s * pause_x,
                self.config.field_delay_max_s * pause_x,
            )
        )

        logger.debug("타자 시작 (길이=%d, typing_x=%.2f)", len(text), typing_x)
        for char in text:
            page.keyboard.type(char)
            time.sleep(
                random.uniform(self.config.typing_min_ms, self.config.typing_max_ms)
                * typing_x
                / 1000.0
            )

    def type_text_with_typos(
        self,
        page: Any,
        selector: str,
        text: str,
        typo_prob: float = 0.15,
        typing_x: float = 1.0,
        pause_x: float = 1.0,
    ) -> None:
        """오타·수정 흉내를 포함해 텍스트를 한 글자씩 인간 리듬으로 입력한다.

        ``type_text`` 와 동일하게 ``page.click(selector)`` 포커스 → 필드 지연 →
        각 문자를 ``page.keyboard.type(char)`` 로 한 글자씩 입력한다. 단, 각 문자
        입력 후 ``random.random() < typo_prob`` 이면 잘못된 문자 1개를 입력한 뒤
        ``page.keyboard.press("Backspace")`` 로 지운다(인간의 오타·수정 흉내).
        올바른 문자는 루프 진입 시 이미 1회 입력되었으므로 재입력하지 않아
        글자 중복이 발생하지 않는다. 입력 중인 문자가 한글이면 오타도 한글 풀에서,
        아니면 알파벳 풀에서 선택한다.

        Args:
            page: Playwright page 객체 (런타임 타입 Any).
            selector: 입력 대상 요소 셀렉터.
            text: 입력할 문자열.
            typo_prob: 오타 발생 확률 (0.0~1.0, 기본 0.15).
            typing_x: 타자 지연 승수 (기본 1.0).
            pause_x: 필드 포커스 후 지연 범위 승수 (기본 1.0).
        """
        page.click(selector)
        # 검색창 잔존 텍스트 강제 클리어 (fill 방식 — SPA 중복 입력 방지).
        self._clear_field(page, selector)
        logger.debug("필드 포커스 후 지연 적용 (selector=%s, pause_x=%.2f)", selector, pause_x)
        time.sleep(
            random.uniform(
                self.config.field_delay_min_s * pause_x,
                self.config.field_delay_max_s * pause_x,
            )
        )

        logger.debug("오타 포함 타자 시작 (길이=%d, typo_prob=%.2f)", len(text), typo_prob)
        for char in text:
            # 원글자는 루프에서 1회만 입력한다. 오타 보정 시 재입력하지 않으므로
            # 글자 중복이 발생하지 않는다 (직전 버그: 재입력으로 1글자 중복).
            page.keyboard.type(char)
            time.sleep(
                random.uniform(self.config.typing_min_ms, self.config.typing_max_ms)
                * typing_x
                / 1000.0
            )
            # typo_prob 확률로 오타·수정 흉내 (인간은 치다가 고침).
            if random.random() < typo_prob:
                wrong = (
                    random.choice(_TYPO_HANGUL)
                    if _is_hangul(char)
                    else random.choice(_TYPO_ALPHA)
                )
                # 잘못 입력 → 백스페이스 (원글자는 상단에서 이미 1회 입력됨).
                # 재입력하지 않으므로 주입 문자열이 원본과 동일하게 유지된다.
                page.keyboard.type(wrong)
                page.keyboard.press("Backspace")
                logger.debug("오타·수정 시뮬레이션 (원본=%r, 오타=%r)", char, wrong)

    def move_mouse_bezier(
        self,
        page: Any,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> None:
        """베지어 곡선으로 마우스를 이동시킨다 (직선 이동 아님).

        시작점→제어점→끝점의 2차 베지어를 ``mouse_steps`` 개로 분할하여
        각 단계마다 ``page.mouse.move`` + 미세 지터 + 짧은 sleep 을 적용한다.

        Args:
            page: Playwright page 객체 (런타임 타입 Any).
            x0, y0: 시작 좌표.
            x1, y1: 끝 좌표.
        """
        p0 = (float(x0), float(y0))
        p2 = (float(x1), float(y1))
        p1 = self._make_control_point(x0, y0, x1, y1)

        steps = self.config.mouse_steps
        logger.debug("베지어 마우스 이동 (steps=%d)", steps)
        for i in range(steps + 1):
            t = i / steps
            bx, by = self._bezier_point(t, p0, p1, p2)
            # 미세 가우시안 지터 (인간은 완벽한 곡선도 아님).
            jx = random.gauss(0.0, self.config.mouse_jitter_px / 3.0)
            jy = random.gauss(0.0, self.config.mouse_jitter_px / 3.0)
            page.mouse.move(bx + jx, by + jy)
            time.sleep(random.uniform(0.004, 0.012))

    def move_mouse_to_element(
        self,
        page: Any,
        selector: str,
        *,
        click: bool = False,
        fail_on_missing: bool = False,
    ) -> tuple[float, float] | None:
        """특정 셀렉터 요소의 중심으로 마우스를 인간적 궤적(베지어)으로 이동한다.

        절차:

        1. ``page.evaluate`` 로 ``selector`` 요소의 bounding box
           (x, y, width, height, 뷰포트 기준) 를 획득한다 (필요 시 요소를
           뷰포트 중앙으로 스크롤).
        2. 중심좌표 ``cx = x + width/2``, ``cy = y + height/2`` 를 계산한다.
        3. 추적 중인 현재 커서 위치(또는 초기 화면 밖 좌표)에서
           ``move_mouse_bezier`` 로 곡선 이동한다. 이동 후 위치를 추적값으로 갱신.
        4. ``click=True`` 이면 중심 위치를 클릭한다 (행동 여부는 호출자가 결정).

        셀렉터를 찾지 못하면 기본적으로 ``None`` 을 반환하며 조용히 무시한다
        (검색 결과 훑기 등 부수효과 경로에서 크래시를 막기 위함).
        ``fail_on_missing=True`` 로 예외를 강제할 수도 있다.

        Args:
            page: Playwright page 객체 (런타임 타입 Any).
            selector: 대상 CSS 셀렉터.
            click: 이동 후 중심 위치 클릭 여부 (기본 False — 호출자가 결정).
            fail_on_missing: 셀렉터 미존재 시 예외 발생 여부 (기본 False).
                True 면 ``ElementNotFoundError``(ValueError 하위) 를 발생시킨다.

        Returns:
            이동한 중심 좌표 ``(cx, cy)``. 요소를 찾지 못하면 ``None``
            (``fail_on_missing=False`` 인 경우).
        """
        box = self._get_element_box(page, selector)
        if box is None:
            if fail_on_missing:
                raise ElementNotFoundError(selector)
            logger.debug("셀렉터 미존재로 이동 생략 (selector=%s)", selector)
            return None

        cx = box["x"] + box["width"] / 2.0
        cy = box["y"] + box["height"] / 2.0
        # 추적 중인 현재 커서 위치(또는 초기 화면 밖)에서 곡선 이동.
        sx, sy = self._mouse_pos
        self.move_mouse_bezier(page, sx, sy, cx, cy)
        # 이동한 위치를 다음 이동의 시작점으로 재사용하도록 추적값 갱신.
        self._mouse_pos = (cx, cy)
        if click:
            page.mouse.click(cx, cy)
            logger.debug(
                "요소 중심 클릭 (selector=%s, cx=%.1f, cy=%.1f)", selector, cx, cy
            )
        return (cx, cy)

    def _get_element_box(self, page: Any, selector: str) -> dict | None:
        """셀렉터 요소의 뷰포트 기준 bounding box 를 dict 로 반환 (없으면 None).

        ``document.querySelector(selector)`` 로 요소를 찾고, 없으면 ``None``.
        있으면 ``scrollIntoView`` 로 뷰포트 중앙으로 스크롤한 뒤
        ``getBoundingClientRect()`` 로 ``x/y/width/height`` 를 구한다.
        ``page.evaluate`` 실패(페이지 닫힘 등)는 ``None`` 으로 안전 처리한다.

        Args:
            page: Playwright page 객체 (런타임 타입 Any).
            selector: 대상 CSS 셀렉터.

        Returns:
            ``{"x": float, "y": float, "width": float, "height": float}`` 또는
            요소/평가 실패 시 ``None``.
        """
        try:
            result = page.evaluate(  # type: ignore[attr-defined]
                "(sel) => {"
                "  const el = document.querySelector(sel);"
                "  if (!el) return null;"
                "  el.scrollIntoView({block: 'center', inline: 'center'});"
                "  const r = el.getBoundingClientRect();"
                "  return {x: r.x, y: r.y, width: r.width, height: r.height};"
                "}",
                selector,
            )
        except Exception:  # evaluate 실패(페이지 언로드 등) — None 으로 안전 처리.
            logger.debug("bounding box 획득 실패 (selector=%s)", selector, exc_info=True)
            return None
        if not isinstance(result, dict):
            return None
        return result

    def think_pause(self) -> None:
        """액션 사이의 무작위 '생각' 대기를 적용한다.

        ``pause_min_s~pause_max_s`` 범위 내에서 무작위 대기한다.
        """
        duration = random.uniform(self.config.pause_min_s, self.config.pause_max_s)
        logger.debug("생각 대기 (%.2fs)", duration)
        time.sleep(duration)

    def random_scroll(self, page: Any, scroll_x: float = 1.0) -> None:
        """확률적으로 스크롤을 수행한다.

        ``random.random() < scroll_prob * scroll_x`` 이면 아래로 무작위 양만큼
        ``page.mouse.wheel`` 로 스크롤한다 (인간의 가끔 스크롤 흉내).
        ``scroll_x`` 는 엔진별 배율 승수(기본 1.0) — 1.0 보다 크면 스크롤이 더
        자주 발생한다 (1.0 이면 기존 동작과 동일).

        Args:
            page: Playwright page 객체 (런타임 타입 Any).
            scroll_x: 스크롤 발생 확률 승수 (기본 1.0).
        """
        if random.random() < self.config.scroll_prob * scroll_x:
            delta = random.randint(120, 480)
            logger.debug("확률적 스크롤 수행 (delta=%dpx, scroll_x=%.2f)", delta, scroll_x)
            page.mouse.wheel(0, delta)
            time.sleep(random.uniform(0.1, 0.4))
        else:
            logger.debug("확률적 스크롤 생략 (이번 턴)")

    def scroll_to_bottom(
        self,
        page: Any,
        scrolls: int = 4,
        scroll_x: float = 1.0,
    ) -> None:
        """확정적으로 여러 회 아래로 스크롤한다 (인간이 결과를 훑는 행위).

        ``scrolls`` 회수만큼 무작위 delta(300~700px)로 ``page.mouse.wheel`` 아래
        스크롤을 수행하고, 회마다 짧은 ``think_pause`` 를 둔다. ``scroll_prob``
        같은 확률 변수를 무시하고 입력 횟수만큼 확정적으로 스크롤한다. ``scroll_x``
        는 엔진별 배율 승수(기본 1.0)로, 로그/확장점으로 보관된다.

        Args:
            page: Playwright page 객체 (런타임 타입 Any).
            scrolls: 확정적 스크롤 횟수 (기본 4).
            scroll_x: 엔진별 배율 승수 (기본 1.0).
        """
        logger.debug("하단 스크롤 시작 (scrolls=%d, scroll_x=%.2f)", scrolls, scroll_x)
        for _ in range(scrolls):
            delta = random.randint(300, 700)
            page.mouse.wheel(0, delta)
            time.sleep(random.uniform(0.1, 0.4))
            # 회마다 짧은 '생각' 대기 (인간이 결과를 읽는 체류).
            self.think_pause()

    def session_gap(self) -> None:
        """검색 세션 사이의 무작위 대기를 적용한다.

        ``session_gap_min_s~session_gap_max_s`` 범위 내에서 무작위 대기하여
        연속 검색 세션을 인간처럼 띄엄띄엄 끊는다.
        """
        duration = random.uniform(
            self.config.session_gap_min_s, self.config.session_gap_max_s
        )
        logger.debug("세션 간격 대기 (%.2fs)", duration)
        time.sleep(duration)

    def pick_click_depth(self) -> int:
        """이번 탐색에서 클릭할 링크 깊이를 무작위로 고른다.

        ``click_depth_min~click_depth_max`` 범위 내 정수를 반환한다.

        Returns:
            선택된 클릭 깊이(정수).
        """
        depth = random.randint(self.config.click_depth_min, self.config.click_depth_max)
        logger.debug("클릭 깊이 선택 (depth=%d)", depth)
        return depth

    def vary_query(self, query: str) -> str:
        """검색어를 무해하게 변형한다 (의미 핵심 토큰 보존).

        ``query_variant_prob`` 확률로만 변형을 적용한다. 미당첨(prob=0 포함)
        시 원본을 그대로 반환한다. 변형은 다음을 포함하되 의미 핵심은 보존한다:
            - 선행/후행 공백 strip
            - 확률적 "최신 " 접두사 부가
            - 소량 동의어 치환표 적용 (예: pdf→PDF, ai→AI)

        Args:
            query: 원본 검색어.

        Returns:
            변형된 검색어 또는 원본 (미변형 시).
        """
        # query_variant_prob 확률로만 변형. 미당첨 시 원본 반환.
        if random.random() >= self.config.query_variant_prob:
            return query

        # 1) 선행/후행 공백 strip (의미 변화 없음).
        variant = query.strip()

        # 2) 확률적 "최신 " 접두사 부가 (의미 핵심 보존).
        if random.random() < _QUERY_PREFIX_PROB:
            variant = "최신 " + variant

        # 3) 소량 동의어 치환표 적용 (핵심 토큰 보존, 표기만 정규화).
        synonyms: dict[str, str] = {"pdf": "PDF", "ai": "AI"}
        for key, value in synonyms.items():
            variant = variant.replace(key, value)

        logger.debug("쿼리 변형 (원본=%r → 변형=%r)", query, variant)
        return variant
