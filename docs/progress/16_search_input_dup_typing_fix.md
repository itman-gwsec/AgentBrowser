# 16. 검색 입력 중복 타이핑 버그 수정 (Bing/Google/DDG 관찰)

## §1. 문제 인지 (2026-08-16)
사용자가 검색 필드 입력 시 **중복 타이핑 에러** 관찰 (Bing 사례).
이전 버그픽스(빙 프리필 `page.fill(selector,"")` 강제클리어)는 재발 없으나,
실제 사용 경로에서 여전히 중복 발생 → 단일 에이전트가 실제 브라우저로 관찰 테스트 수행.

## §2. 관찰 결과 (실측: /tmp/search_dup_test.json)
각 엔진 `Humanizer.type_text_with_typos("test query", typo_prob=0.15)` 입력 후 `page.input_value()`:
- Bing `#sb_form_q` → `testt query` (중복)
- Google `textarea[name=q]` → `ttest query` (중복, **캡차/차단 없음** — 실제 headed Chrome 봇탐지 통과)
- DDG `#search_form_input` → `tesst querry` (중복)
- 격리 테스트(typo_prob=0)에서는 `_clear_field` 정상 동작 → 프리필 중복 아님.

## §3. 근본 원인
`src/core/humanizer.py` `type_text_with_typos`(L273~291) 오타보정 경로 버그:
루프 상단에서 `page.keyboard.type(char)` 로 원글자 1회 입력한 뒤,
오타 발생 시 `wrong → Backspace → page.keyboard.type(char)` 로 **원글자를 다시 침**.
결과: 원글자 1개가 중복 (typo_prob 기본 0.15 → 쿼리 ~15% 글자 중복). 엔진 무관 코어 버그.
사용자가 본 Bing 중복도 이 경로일 가능성 높음 (빙 프리필 문제와는 별개).

## §4. 수정 (TDD)
- `type_text_with_typos`: 오타 시 원글자 재타입 삭제, `wrong → Backspace` 만 수행 (상단 1회 입력 유지).
- `type_text`(L189~233)는 오타 분기 자체가 없어 이미 정상 — 점검만.
- 신규 테스트 3건 (typo 강제/미발생/300회 스트레스) → RED 확인 후 GREEN.

## §5. 검증
- pytest `tests/unit`: **54 passed** (신규 3건 포함).
- ruff: `All checks passed!`.
- 실제 headed Chrome 검증 (`scripts/verify_dup_fix.py`, typo_prob=0.15):
  Bing/Google/DDG 모두 `"test query"` (중복 없음, all_clean=true).
- DDG 부수 발견: 코어 `DuckDuckGoSearch` 가 `#searchbox` 셀렉터 사용하나 실제는 `#search_form_input` →
  human-like 타이핑 침묵 누락, URL쿼리만 사용됨 (별도 이슈, 이번 미수정).

## §6. Google 검색 테스트 (사용자 지시 예외)
이번만 Google 검색 테스트 허용 → 차단/캡차 없이 정상 입력. 봇탐지 회피(인간행동 시뮬레이션) 유효성 실증.
단 운영 원칙(구글 제외)은 유지 — 테스트 목적 한정.
