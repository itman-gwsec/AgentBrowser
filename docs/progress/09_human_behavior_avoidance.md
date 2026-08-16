# 09. 인간 행동 모방 검색 봇탐지 회피 설계 로그

> 작성 롤: analyst (R01) — 모든 주장은 실제 소스 코드·테스트 실행 결과에 기반.
> 대상 커밋: humanizer + search + runner 통합 (행동 패턴 시뮬레이션).
> 검증 환경: 로컬 `.venv` (Python 3.11), 커밋 직전 실제 실행.

---

## §1. 목적

- 사용자 명시 요구: 실제(헤드풀) Chrome 기반 에이전트가 검색 시 봇으로 오인되지 않도록, 인간 행동을 모방하는 시뮬레이션 계층을 도입한다.
- 구현 범위 3종:
  1. 인간유사 입력·이동·대기·스크롤을 수행하는 `Humanizer` (`src/core/humanizer.py`).
  2. 엔진별 인간유사 검색을 수행하는 `SearchEngine` / `SearchDispatcher` (`src/core/search.py`).
  3. `runner.run()` 의 기존 CDP 직접 제어 경로를 위 두 계층으로 우회시키는 통합 (`src/agent/runner/__init__.py`).

---

## §2. 탐지 벡터 분석

봇 탐지 벡터는 크게 3종으로 분류된다. 본 프로젝트는 **헤드풀 real Chrome**을 사용하므로 벡터별 회피 소요가 다르다.

### ① 정적 지문 (UA / WebGL / Canvas 지문 등)
- 회피 대상 아님. 헤드풀 real Chrome 이 노출하는 UA·WebGL·Canvas 는 실제 인간 브라우저와 동일하다. 별도 위조 필요 없음.

### ② 네트워크 (TLS 지문 / 헤더 순서 / IP 등)
- 회피 대상 아님. 실제 브라우저 프로세스가 생성하는 TLS 핸드셰이크·헤더는 인간과 동일하다. 프록시/IP 조작 없이 인간과 동일.

### ③ 행동 패턴 (타자 리듬 / 마우스 궤적 / 액션 간 대기 / 스크롤)
- **유일한 회피 대상.** 기계적 균일성(즉시 입력, 직선 마우스, 0 대기)이 봇 시그널이 되므로, 이 패턴만 위조한다.

> 결론: ①②는 real Chrome 이 인간과 동일하여 미처리, ③만 Python agent 레이어에서 시뮬레이션한다 (§4 설계 제약과 일치).

---

## §3. Humanizer 설계 (src/core/humanizer.py, 224라인)

인간유사 동작 엔진. Playwright `page` 객체를 메서드 인자로 받아 동작 (`cdp_bridge` 가 이미 Playwright 기반이므로 호환).

### 3.1 HumanizerConfig (9필드, pydantic v2)
| 필드 | 기본값 | 의미 |
|------|--------|------|
| typing_min_ms / typing_max_ms | 40 / 180 | 문자 간 타자 지연(ms) 범위 |
| mouse_steps | 24 | 베지어 궤적 분할 단계 수 |
| mouse_jitter_px | 3.0 | 궤적 미세 가우시안 지터(픽셀) |
| pause_min_s / pause_max_s | 0.3 / 2.5 | 액션 간 '생각' 대기(초) 범위 |
| scroll_prob | 0.4 | 확률적 스크롤 발생 확률(0.0~1.0) |
| field_delay_min_s / field_delay_max_s | 0.2 / 0.8 | 필드 포커스 후 타이핑 시작 전 지연(초) |

- `model_config = {"extra": "forbid"}` 로 추가 필드 거부 (L63).
- 모든 딜레이/확률 필드는 `Field(ge=...)` / `le=...` 제약 보유.

### 3.2 시뮬레이션 4종 (공개 메서드)
1. `type_text(page, selector, text)` (L141~): selector 클릭 → 필드 지연 → 한 글자씩 `page.keyboard.type` + 무작위 타자 지연. 붙여넣기 아님.
2. `move_mouse_bezier(page, x0,y0,x1,y1)` (L167~): 시작→제어점→끝 2차 베지어를 `mouse_steps` 분할, 각 단계 `page.mouse.move` + 가우시안 지터 + 짧은 sleep. 직선 이동 아님. 제어점은 `_make_control_point` (L108~) 가 중점 수직 오프셋으로 생성 (굽힘량 = 거리의 ~20%).
3. `think_pause()` (L200~): `pause_min_s ~ pause_max_s` 무작위 대기.
4. `random_scroll(page)` (L209~): `random.random() < scroll_prob` 이면 `page.mouse.wheel` 로 무작위(120~480px) 아래 스크롤.

- 베지어 보간은 순수 함수 `_bezier_point` (L83~) 로 분리 (테스트 용이).
- 설계 제약 (L12~14 명시): 익스텐션 JS 회피 로직 미사용, `time.sleep` 기반 인간 리듬은 의도적 유지.

---

## §4. Search 설계 (src/core/search.py, 296라인)

엔진별 인간유사 검색 + 캡차 HITL 재사용.

### 4.1 SearchConfig (pydantic v2)
- `engine: Literal["google","duckduckgo","bing"]` (기본 `"duckduckgo"` — 차단 관대).
- `query_param: dict` (google/ddg/bing 모두 `"q"`).
- `result_wait_min_s / result_wait_max_s` (기본 1.0 / 3.0).
- `model_validator` (L63~) 로 `result_wait_min_s > result_wait_max_s` 거부 (min <= max 불변식).

### 4.2 SearchEngine (ABC, L78~)
- 추상 `search(page, humanizer, query) -> str`.
- 공통 메서드: `_build_url` (쿼리 인코딩, L112~), `_navigate` (goto + think_pause 위임, L124~), `_wait_results` (무작위 대기, L139~), `_summarize` (결과 요약 문자열 스텁, L145~).
- 3종 구현:
  - `GoogleSearch` (L161~): base `https://www.google.com/search`, 검색창 `textarea[name=q], input[name=q]`.
  - `DuckDuckGoSearch` (L188~): base `https://duckduckgo.com/`, `#searchbox`.
  - `BingSearch` (L210~): base `https://www.bing.com/search`, `#sb_form_q`.
  - 각 `search()` 는 URL 쿼리 이동(fallback 보장) 후 인간유사 타이핑 + Enter, selector 미존재 시 URL 결과로 대체(예외 허용).

### 4.3 SearchDispatcher (L232~)
- `_ENGINE_MAP` 으로 engine → 클래스 매핑, `_select_engine()` 로 인스턴스 선택.
- `run(page, query) -> str | HITLRequest` (L270~):
  1. engine 선택 → `search()` (humanizer 연동).
  2. `cdp_bridge` 있으면 `detect_and_request_hitl()` **재사용** — 캡차 탐지 시 `HITLRequest` 반환 (단일 책임: 탐지는 cdp_bridge 가 담당).
  3. 미탐지/브리지 없으면 결과 요약 `str` 반환.

### 4.4 runner 통합 (src/agent/runner/__init__.py)
- `Runner.run(handoff)` (L45~) 기존 `self.cdp.control(handoff)` 직접 경로 대신, 지연 import로 `CDPBridge`·`Humanizer`·`SearchConfig`·`SearchDispatcher` 를 로드하여 인간유사 검색 경로를 **우선** 수행한다 (L82~107).
- 실패 시 `result` 만 반환(안전 fallback), `HITLRequest` 시 `[HITL] ...` 문자열로 병합.
- `CDPBridge.control()` 메서드는 `cdp_bridge.py` 에 유지(호환성, 타 코드 직접 호출 가능).

### 4.5 설계 제약 준수 (§4)
- 익스텐션 JS 회피 로직 미사용. Python agent 레이어(humanizer/search/runner)에서만 구현 (humanizer.py L12~14, search.py L8~9 명시).
- `time.sleep` 기반 인간 리듬은 의도적 유지.

---

## §5. 한계와 후속과제 (사용자 명시 맹점 — 정직 기록)

행동 위조 범위 밖의 한계 3종과 대안을 명시한다. 표기는 난이도/공수 관점 ("불가능" 지양).

### 5.1 행동 위조 범위 밖의 한계
- **CDP 흔적**: Playwright CDP attach 시 페이지에 `window.cdc_*` / `Runtime.Profiler` 도메인 활성화 흔적이 노출된다. 행동 시뮬레이션만으로는 차단 불가 (공수: CDP 포기 필요).
- **서버측 패턴**: 쿼리 분포·세션 간격·클릭 깊이 등 장기 패턴은 단발 시뮬레이션으로 불가 (공수: 세션 단위 로그/리플레이 필요).
- **엔진별 가중치(B)**: 이번 위임은 기본 동일 동작만 구현. Google=지연↑ / DDG=관대 등 가중 미적용 (공수: 중).

### 5.2 CDP 대체 대안 (사용자 논의 — 후속 phase 과제 분리)
- 일렉트론 신규개발은 과잉 (공수 대). 현실적 대안 2종:
  1. **OS 네이티브 입력** (osascript / CGEvent / xdotool): CDP attach 포기 → 브라우저 입장 100% 진짜 인간 입력.
  2. **익스텐션 scripting API**: 단 §4 위반 소지(회피 금지) → 채택 보류.
- → 후속 phase 에서 (1) 우선 검토.

---

## §6. 검증

- ruff: `ruff check .` → **All checks passed!** (전체 프로젝트, 신규/수정 5파일 포함).
- pytest: `python -m pytest` → **37 passed** (기존 32 + humanizer 신규 6 + search 신규 5, 실행 1.58s).
- 위 수치는 커밋 직전 로컬 `.venv` 에서 실제 실행한 결과를 반영.

---

## §7. 커밋 대상 파일 (6종)
- `src/core/humanizer.py` (신규, 224라인)
- `src/core/search.py` (신규, 296라인)
- `src/agent/runner/__init__.py` (수정)
- `tests/unit/test_humanizer.py` (신규)
- `tests/unit/test_search.py` (신규)
- `docs/progress/09_human_behavior_avoidance.md` (신규, 본 문서)
