# 13. Phase 5 — 인간 행동 시퀀스 보강 및 E2E 검증

## §1. 목적
Phase 3/4로 구현된 인간 행동 모방(타이핑 리듬, 스크롤, 클릭, 세션 간격)이
실제로 인간처럼 보이는지 검증하고, 부족한 부분을 보강한다.
사용자 지적(2026-08-15): "구글 검색 후 스크롤 없이 바로 닫는 것은 인간적이지
않고 위험하다. 결과를 읽는 시간과 스크롤하여 하단까지 돌려보는 행위가
들어가야 하며, 텍스트 입력도 적절한 리듬·속도로 지우기도 하며 위장해야 한다."

## §2. 선행 진단 (적용 누락 발견)
설계 문서(09/11)에는 인간 행동 개념이 있었으나, `search.py`가 `humanizer`를
충분히 엮지 않은 **적용 누락** 상태였다. 구체적 4가지:
1. 지우기 위장 메서드 부재 — `type_text`는 한 글자씩 치기만 함 (오타·수정 없음)
2. `move_mouse_bezier`가 `search.py` 어디서도 호출되지 않음 (0회)
3. `_post_search`가 `random_scroll`을 1회·확률적(40%)만 호출 — 하단까지 안 돌림
4. 결과 읽기 체류(`think_pause`) 거의 없음, 클릭이 `page.goto` 즉시 이동(복귀 없음)

## §3. 보강 내역
- `humanizer.type_text_with_typos(typo_prob=0.15)`: 각 문자 입력 후 확률적으로
  오타 1자 입력 → `Backspace` → 정확 문자 재입력 (인간의 오타·수정 흉내).
  한글 입력 시 한글 유사음 풀(`_TYPO_HANGUL`), 영문 시 알파벳 풀(`_TYPO_ALPHA`).
- `humanizer.scroll_to_bottom(scrolls=4)`: 확정적 4회 하단 스크롤 + 회마다
  짧은 `think_pause` (확률 무시 → 다회 보장).
- `search._post_search` 재구성 시퀀스:
  `[대기 → think_pause(훑기 전) → scroll_to_bottom(4회) → think_pause(읽기 체류)
   → extract_links → hover 클릭 → think_pause(마무리)]`
- `type_text → type_text_with_typos` 교체 3곳 (Google/DDG/Bing, typo_prob=0.15).
- `_apply_click_depth` 변경: `page.goto` 즉시 이동 폐기 →
  `move_mouse_bezier`로 좌표 획득 후 hover, depth 중 1개만 새 탭 열기→닫기
  (인간이 링크 훑어보고 닫는 행위).

## §4. E2E 검증 결과
실제 headed Chrome(봇 탐지 플래그 없음) 기동 → 인간 행동 시퀀스 적용:
- DuckDuckGo: **10건** 링크 추출 성공 (증거: `/tmp/verify_ddg.json`)
- Yahoo: **7건** 링크 추출 성공 (증거: `/tmp/verify_yahoo.json`)
- 스크롤 하단 + 체류 + 지우기 위장 시퀀스 포함 검증 완료.

**구글 검증은 사용자 지시로 중단함**: 차단 리스크(비정상 트래픽/캡차)가 크고,
덕덕고/야후로 셀렉터 정밀도와 인간 행동 시퀀스 검증이 충분히 완료되어
굳이 수행할 필요가 없음. 차후 필요 시 별도 단계에서 수행.

## §5. 검증 지표
- `ruff check src tests` → All checks passed! (에러 0)
- `pytest` → 58 passed (기존 56 + 신규 2: 지우기위장 Backspace 호출, 하단스크롤 wheel 3회)

## §6. 차후 과제
- 구글 검증 (차후, 차단 대비 로직 포함)
- 실제 다중 검색 세션에서 체류 시간·스크롤 횟수 튜닝 (로그 기반)
- 엔진별 selector 실브라우저 정밀도 추가 검증 (DDG/Yahoo 외 Bing 등)
