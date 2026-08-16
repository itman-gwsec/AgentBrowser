# 14. 버그픽스: 검색창 중복입력 해결 + 개별 페이지 humanizer 적용

> 작성 롤: analyst (R01) — 모든 주장은 실측 evidence 기반.
> 검증 근거: 실제 headed Chrome 입력 검증, ruff 클린, pytest 60 passed.

## §1. 목적

에이전트 브라우저 실제 사용 중 발견된 2가지 버그를 수정한다.

1. **검색창 중복 입력** — 사용자가 첨부한 이미지에서, 이전 쿼리 잔존 텍스트 위에 새 쿼리가 덧붙여진 것이 증명됨 (증거: `/tmp/bing_clear_verify.png`, 입력값 `value='qwen3.8에 대한 심층 분석'` 단일값).
2. **개별 페이지 humanizer 미적용** — 검색 결과에서 링크를 새 탭으로 열어 이동한 경우, 이동한 페이지에 humanizer(스크롤/체류/마우스)가 적용되지 않아 개별 사이트 봇 탐지/Cloudflare 방어가 누락됨. 사용자 지적(2026-08-15): "검색된 페이지로 이동한 경우 해당 페이지에서 humanizer 미적용 + 개별 사이트 봇탐지/Cloudflare 방어 필요".

## §2. 버그 A: 검색창 중복 입력

- **원인**: 기존 `type_text`/`type_text_with_typos` 는 `page.click(selector)` 후 바로 타이핑만 수행. 검색창 초기화는 `Control+a`/`Backspace`(select-all) 방식에 의존했으나, Bing 등 SPA 검색창은 value 를 자체 관리하여 select-all 이 의도대로 동작하지 않음.
- **수정**: `Humanizer._clear_field(page, selector)` 신규 추가 → `page.fill(selector, "")` 강제 클리어로 교체. `type_text`/`type_text_with_typos` 가 `page.click` 직후 `self._clear_field(page, selector)` 를 호출. `fill` 실패(셀렉터 미존재 등) 시 `except` 로 debug 로그만 남기고 타자 계속 (타자에 영향 없음).
- **증거(실측)**: 실제 headed Chrome 검증에서 잔존 텍스트(`OLDTEXT`) 위에 입력 시 최종 `value='qwen3.8에 대한 심층 분석'` 만 남음 — 중복 없음 증명 (`/tmp/bing_clear_verify.png`).
- **관련 파일**: `src/core/humanizer.py`, `tests/unit/test_humanizer.py`(`test_type_text_clears_existing` 신규).

## §3. 버그 B: 개별 페이지 humanizer 미적용

- **원인**: `SearchEngine._apply_click_depth` 는 결과 링크 중 1개를 새 탭(`page.context.new_page`)으로 열고 **즉시 닫기만** 했음. 이동한 개별 사이트(새 탭)에는 humanizer 행동이 전혀 적용되지 않음.
- **수정**: 새 탭 `goto` 직후 `humanizer.scroll_to_bottom(new_tab, scrolls=2)` + `humanizer.think_pause()` + `humanizer.move_mouse_bezier(new_tab, ...)` 를 적용한 뒤 닫음. Cloudflare challenge 등 예외는 `try/except` 로 무시 (크래시 없이 통과).
- **의도**: 결과 페이지뿐 아니라 이동한 개별 사이트에서도 스크롤/체류/마우스 인간 행동을 수행 → 개별 사이트 봇 탐지/Cloudflare 방어 보강.
- **관련 파일**: `src/core/search.py`, `tests/unit/test_search.py`(`test_apply_click_depth_applies_humanizer_on_new_tab` 신규 + `test_search_clicks_depth` 보강).

## §4. 검증

- **ruff**: 클린 (`ruff check` — All checks passed!).
- **pytest**: 60 passed (기존 59 + 신규 1: 새 탭 humanizer 적용 테스트).
- **실측 Chrome**: `input_value()` 검증으로 중복 입력 없음 확인 (§2 증거).

## §5. 차후 과제

1. **Cloudflare challenge 능동 대응**: 현재는 예외를 무시(통과)만 함. challenge 감지 시 일정 시간 대기 후 재시도하는 능동 회피 추가 필요.
2. **엔진별 입력 셀렉터 정밀화**: `fill(selector, "")` 의 셀렉터가 엔진별로 다를 수 있음. 엔진별 정밀 셀렉터 매핑 보강.
3. **개별 페이지 체류시간 튜닝**: 새 탭 humanizer 적용 시 `scrolls=2` / `think_pause` 횟수를 사이트 성격(정적/동적)별로 튜닝.
