# 10. 엔진별 가중치 + 서버측 패턴 완화 설계 로그

> 작성 롤: analyst (R01) — 모든 주장은 실제 소스 코드·테스트 실행 결과에 기반.
> 대상 커밋: 검색 회피 강화 (엔진별 가중치 B + 서버측 패턴 완화).
> 검증 환경: 로컬 `.venv` (Python 3.11), 커밋 직전 실제 실행.
> 선행 문서: `09_human_behavior_avoidance.md` (행동 패턴 ③ 시뮬레이션).

---

## §1. 목적

- 사용자 명시 요구 (재인용): "지속적 검색 실패로 인한 정보 신뢰도 하락 방지" 가 목표.
- 이를 위해 **서버측 패턴 완화**에 집중한다. 09 문서에서 "후속과제(공수: 중)"로 분류했던 두 항목을 이번 위임에서 실제 구현한다:
  1. 엔진별 가중치(B) — Google=지연↑ / DDG=관대 기본 / Bing=중간.
  2. 서버측 장기 패턴 — 세션 간격·쿼리 분포·클릭 깊이.
- 행동 패턴(③) 시뮬레이션은 09 에서 완료. 본 문서는 그 위에 엔진별 배율과 장기 패턴 변수를 덧붙여 실패율을 낮춘다.

---

## §2. 탐지 벡터 재정리

09 문서의 3종 분류를 서버측 관점에서 재정리한다.

### ① 정적 지문 (UA / WebGL / Canvas)
- 회피 대상 아님. 헤드풀 real Chrome 이 인간과 동일.

### ② 네트워크 (TLS / 헤더 순서 / IP)
- 회피 대상 아님. 실제 브라우저 프로세스가 생성하는 핸드셰이크·헤더는 인간과 동일.

### ③ 행동 패턴 (타자 리듬 / 궤적 / 대기 / 스크롤)
- 09 에서 `Humanizer` + `SearchEngine` 으로 구현 완료.

### ④ 서버측 패턴 (장기, 본 위임 대상)
- 단발 요청이 아닌 **여러 검색에 걸친 장기 시그널**: 동일 쿼리 반복, 세션 간격 균일, 클릭 깊이 고정.
- 09 문서 §5.1 에서 "단발 시뮬레이션으로 불가"로 분류했던 항목이나, 세션 단위 변수(간격/쿼리분포/클릭깊이)는 Python agent 레이어에서 충분히 위조 가능하므로 이번에 적용한다.

> 결론: ①② 미처리, ③은 선행 구현, **④가 이번 대상**.

---

## §3. 엔진별 가중치 설계 (src/core/search.py)

### 3.1 engine_weights 표 (SearchConfig, L65~71)
| 엔진 | typing_x | pause_x | scroll_x | wait_x | 성격 |
|------|----------|---------|----------|--------|------|
| google | 1.4 | 1.6 | 1.5 | 1.5 | 감시 엄격 → 리듬 지연 상향 |
| duckduckgo | 1.0 | 1.0 | 1.0 | 1.0 | 기준(관대) |
| bing | 1.2 | 1.3 | 1.2 | 1.2 | 중간값 |

- `SearchConfig.engine_weights` 는 `dict[str, dict[str, float]]` (pydantic v2, `extra=forbid` 유지).
- 배율 1.0 은 기존 동작과 동일. 1.0 초과 시 해당 동작이 더 느리게/자주 발생.

### 3.2 적용 방식 (4개 승수의 실제 반영 지점)
- `type_text(typing_x, pause_x)` (humanizer.py L161~): 타자 지연 승수 `typing_x`, 필드 포커스 후 지연 범위 승수 `pause_x`. 각 검색 엔진 `search()` 가 `weights["typing_x"]`/`weights["pause_x"]` 를 전달 (search.py L194~200 등).
- `random_scroll(scroll_x)` (humanizer.py L247~): `scroll_prob * scroll_x` 확률로 스크롤. `scroll_x > 1.0` 이면 스크롤이 더 자주 발생. `search()` 가 `weights["scroll_x"]` 전달 (search.py L206 등).
- `_wait_results(wait_x)` (search.py L150~): 결과 대기 `base * wait_x`. `SearchEngine._wait_results` 가 `engine_weights[engine_name]["wait_x"]` 를 곱한다 (search.py L153~).
- **클릭 깊이 가중은 미포함**: `engine_weights` 에 `click_x` 항목 없음. 클릭 깊이는 §4.3 의 별도 무작위 변수로 처리.

> Google 은 4개 승수 모두 상향(지연↑·스크롤↑) → 봇 감시가 엄격한 엔진에서 인간 리듬을 더 두드러지게 흉내. DDG 는 기준, Bing 은 그 사이.

---

## §4. 서버측 패턴 완화 (인간유사 장기 변수)

### 4.1 session_gap — 세션 간격 (Humanizer, L267~)
- `session_gap_min_s ~ session_gap_max_s` 범위(기본 **5.0 ~ 20.0초**) 내 무작위 대기.
- `SearchDispatcher.run()` 이 검색 직전에 호출 (search.py L327) → 연속 검색 세션을 인간처럼 띄엄띄엄 끊는다.

### 4.2 vary_query — 쿼리 분포 (Humanizer, L291~)
- `query_variant_prob` 확률(기본 0.3)로만 변형, 미당첨 시 원본 반환.
- 변형: 선행/후행 공백 strip + 확률적 "최신 " 접두사(확률 0.5) + 소량 동의어 표기 정규화(pdf→PDF, ai→AI). 의미 핵심 토큰 보존.
- `SearchDispatcher.run()` 이 검색 직후에 호출 (search.py L332). 반환값은 다음 턴에 소비 (로깅/준비 단계, 현재 run 반환값은 기존 결과 문자열 유지).

### 4.3 pick_click_depth — 클릭 깊이 (Humanizer, L279~)
- `click_depth_min ~ click_depth_max` 범위(기본 **1 ~ 4**) 내 정수 무작위 선택.
- 메서드는 추가 완료. 검색 루프 내 실제 링크 클릭 탐색으로의 배선은 차후과제 (현재 `run()` 은 `session_gap()`·`vary_query()` 만 호출, `pick_click_depth()` 는 미호출).

> 정리: ④ 서버측 패턴 중 세션 간격·쿼리 분포는 `run()` 에 즉시 배선 완료, 클릭 깊이는 변수·메서드 확보 완료(배선 후속).

---

## §5. 검증

- ruff: `ruff check src/core/humanizer.py src/core/search.py tests/unit/test_humanizer.py tests/unit/test_search.py` → **All checks passed!**
- pytest: `python -m pytest` → **42 passed** (실행 1.58s). 전체 스위트 기준 실측.
- CDP 흔적: 이전 E2E 실측에서 `window.cdc_*` / Playwright 흔적이 **비어있음** 확인 → OS 네이티브 입력은 불필요로 확정, 이번 범위 아님 (09 §5.2 대안(1) 보류 사유 소멸).

---

## §6. 차후 과제

- 실제 LLM 연동: 현재 검색 결과 요약은 `[STUB]` (MVP 스텁, `_summarize` 가 URL/엔진/쿼리만 반환). 의미 추출은 미구현.
- 익스텐션 배너 UI: 차단/캡차 알림 노출용 UI. 현재 HITL 요청만 반환.
- 결과 파싱/추출: 검색 결과 본문→구조화 데이터 파싱. `_summarize` 스텁 해소 필요.
- 장기 세션 패턴 학습: 누적 세션 로그 기반 쿼리 분포/간격 자동 튜닝. 현재는 고정 범위 무작위.
- 클릭 깊이 배선: `pick_click_depth()` 를 `run()` 검색 루프에 실제 링크 탐색으로 연결.

---

## §7. 커밋 대상 파일 (5종)

- `src/core/humanizer.py` (수정: session_gap/pick_click_depth/vary_query + 배율 인자)
- `src/core/search.py` (수정: engine_weights + SearchDispatcher.run 배선)
- `tests/unit/test_humanizer.py` (수정: 신규 메서드 검증)
- `tests/unit/test_search.py` (수정: engine_weights 검증)
- `docs/progress/10_engine_weighted_avoidance.md` (신규, 본 문서)

> 제외: `scripts/test_qwen_search.py` (이전 실패 위임 잔재, 불필요 — 커밋 대상 아님, untracked 로 잔류).
