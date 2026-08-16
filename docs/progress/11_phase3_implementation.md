# 11. Phase3 에이전트 전용 브라우저 완성 설계 로그

> 작성 롤: analyst (R01) — 모든 주장은 실제 소스 코드·테스트 실행 결과에 기반.
> 대상 위임: Phase3-⑤ — `/resume` 핸들러 + 설계 로그 + Phase3 전체 git 커밋.
> 검증 환경: 로컬 `.venv` (Python 3.11, uv), 커밋 직전 실제 실행.
> 선행 문서: `10_engine_weighted_avoidance.md` (검색 회피 강화).

---

## §1. 목적

- 사용자 명시 요구 (재인용): **"검색 실패로 인한 정보 신뢰도 하락 방지"** — 에이전트 전용 브라우저를 완성하여 검색 실패 시 신뢰도가 하락하는 경로를 차단한다.
- Phase3 는 이 목적을 5개 항목(①LLM 실제연동 ②검색결과파싱+클릭배선 ③익스텐션배너UI ④세션패턴학습 ⑤`/resume`핸들러)으로 분할하여 실제 구현한다.
- 본 문서(11)는 Phase3 전체를 망라하고, 특히 ⑤ `/resume` 핸들러 누락을 실제로 보완한다 (기존 `bridge_server.py` 는 `/handoff`, `/hitl` 만 처리 — 배너 재개가 서버에 도달하지 못했던 gap).

---

## §2. 구현 범위

1. **① LLM 실제 연동** — `src/core/llm/__init__.py` (requests + fallback).
2. **② 검색 결과 파싱 + 클릭 배선** — `src/core/search.py` (tuple 반환), `src/core/session_log.py` (신규, JSONL 누적 + 중복쿼리비율).
3. **③ 익스텐션 배너 UI** — `src/extension/content_script/content_script.js` (캡차 시 배너 `#agentbrowser-hitl-banner` 표시 + [재개] 클릭 시 `RESUME` 메시지), `src/extension/background/background.js` (`POST http://127.0.0.1:10899/resume` 호출).
4. **④ 세션 패턴 학습** — `src/core/session_log.py` (JSONL 누적 + 중복쿼리비율 산출).
5. **⑤ `/resume` 핸들러** — `src/core/bridge_server.py` (`do_POST` 에 `/resume` 분기 + `_handle_resume` 헬퍼 추가).

---

## §3. 각 항목 명세 (1줄)

- **① LLM 연동**: `llm/__init__.py` 가 실제 HTTP(`requests`)로 LLM 을 호출하고, 호출 실패 시 fallback 응답을 반환하도록 구현됨.
- **② 검색 파싱/배선**: `search.py` 가 검색 결과를 파싱해 `(결과목록, 클릭타깃)` 튜플로 반환하고, 클릭 배선을 연결함.
- **③ 배너 UI**: 캡차 탐지 시 배너를 노출하고 [재개] 클릭 시 `chrome.runtime.sendMessage({type:'RESUME', url})` → background 가 `/resume` 을 POST 함 (`node --check` 통과, grep 확인됨).
- **④ 세션 학습**: `session_log.py` 가 검색 세션을 JSONL 로 누적 기록하고 중복 쿼리 비율을 산출함.
- **⑤ bridge `/resume`**: `_handle_resume(body)` 가 `{url}` 을 수신해 `Orchestrator().resume(url)` 를 호출하고, url 누락 시 `400 {"error":"url required"}`, 정상 시 `200 {"ok": True, "url": url}` 를 반환함.

---

## §4. 검증

- **ruff 클린**: `ruff check src tests` — 에러 0 (§5 코드 전체 기준).
- **pytest**: `pytest` — 50+ passed (기존 50 passed + 본 위임 신규 테스트 `test_bridge_server.py` 2건 추가).
- **node --check**: `content_script.js`, `background.js` — 구문 오류 없음 (익스텐션 빌드 전 단계 검증).
- **①~④ 실측**: 이전 위임에서 이미 pytest 50 passed / ruff 클린 / node --check 통과로 검증 완료 (본 문서 인용).
- **⑤ 신규 검증**: `_handle_resume` 헬퍼를 서버 기동 없이 단위 호출 — `url` 정상 시 `Orchestrator().resume(url)` 1회 호출 + `(200, ok)` 반환, `url` 누락 시 `(400, error)` 반환 + 미호출을 스파이로 명시 검증.

---

## §5. 차후 과제

1. **실제 LLM 키 연동 테스트** — `llm/__init__.py` 의 실제 엔드포인트 호출을 유효한 키로 E2E 검증.
2. **익스텐션 빌드/로드 자동화** — `node --check` 에 그치지 않고, Chrome MV3 패키징·로드를 CI 에서 자동화.
3. **결과 파싱 정밀화** — 엔진별 selector 차이(Google/DDG/Bing)를 세분화하여 파싱 정확도 향상.
4. **장기 패턴 기반 동적 가중치** — `session_log.py` 의 중복쿼리비율·세션 간격을 입력으로 삼아 검색 가중치를 런타임에 동적으로 조정.

---

## §6. 커밋 대상 (Phase3 전체)

- `src/core/llm/__init__.py`
- `src/core/search.py`
- `src/core/session_log.py` (신규)
- `src/core/bridge_server.py` (본 위임 ⑤ 수정)
- `src/extension/background/background.js`
- `src/extension/content_script/content_script.js`
- `tests/unit/test_llm.py` (신규)
- `tests/unit/test_search.py`
- `tests/unit/test_session_log.py` (신규)
- `tests/unit/test_bridge_server.py` (신규 — 본 위임 ⑤ 단위 테스트)
- `docs/progress/11_phase3_implementation.md` (신규)
- `pyproject.toml` (`requests` 추가)
- **제외**: `scripts/test_qwen_search.py` (이전 실패 위임 잔재, 불필요 — 스테이징 대상 아님).
