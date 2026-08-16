---

## 부록: 분석 후속 검증에 의한 정정 (2026-08-16)

본 리포트 작성 후 Rec#1·#2 권고 이행 과정에서 **Runner 판정에 오류**가 발견되어 정정한다.

### 정정 1 — Runner는 "완전 스텁"이 아님 (실제 CDP+검색 구현됨)
- 본 리포트 §요약/§3/§8/§9 에서 `Runner.run()`을 "LLM 텍스트 반환만 하는 스텁, plan→action 제어 미구현"으로 판정했으나, **실제 소스(`src/agent/runner/__init__.py`)는 이미 실제 제어 경로를 포함**한다:
  - `Runner.__init__(llm, cdp_bridge)` — `cdp_bridge` 주입(DI) 지원 (이미 적용, Rec#1에서 새로 리팩터한 것 아님)
  - `run()` L95~119: `CDPBridge().connect()` → `Humanizer()` → `SearchDispatcher.run(page, query)` 로 **실제 headed Chrome 검색 수행**, 캡차/HITL 시 안전 fallback 처리
- 따라서 "검색·조회·봇회피 브라우징 대행(R1~R4)" 목적은 **현재 상태로 이미 사용 가능**하다.
- **진짜 미완은 "plan executor" 하나뿐**: LLM이 짠 액션 계획(텍스트)을 실제 클릭/타이핑으로 자동 실행하는 경로. 이 부분만 미구현이며, 이를 "Runner 스텁"으로 총칭한 것은 부정확했다.

### 정정 2 — test_handoff_endpoint Timeout 원인 (고확신 사실로 격상)
- 본 리포트는 "Timeout 추정"으로 보수 표기했으나, 코드 체인(`bridge_server`→`orchestrator`→`runner.run`→`CDPBridge().connect()` 실제 Chrome spawn)이 명확히 확인됨. Rec#1에서 `Runner`가 `cdp_bridge`를 주입받도록 하여 테스트는 mock bridge 주입으로 우회 → **Timeout 해소·pytest 0-fail 달성(78 passed)**.

### 정정 3 — 권고 이행 결과 (Rec#1·#2 완료)
- **Rec#1**: M5 미커밋 작업트리의 5실패 → 재측정 1실패(`test_bridge_server`의 `mock` import 누락 + `bridge_server.py` UP037 따옴표)를 수정 → **pytest 78 passed / 0 failed, ruff 0 에러** 확정.
- **Rec#2**: `pyproject` 보강 — `playwright` 런타임 의존성 추가, `mypy`+`pytest-cov` dev 의존성 추가, `addopts`에 `--cov` 설정. 실측 커버리지 **전체 76%** (낮은 모듈: `cdp_bridge 50%`, `launcher 45%`, `browser/__init__ 0%`).
- **Rec#3 보류**: 사용자 결정으로 "현재 개발 결과 = v1 완결, 나머지(plan executor, R5 협업 UI)는 추후 구현"으로 확정. 따라서 본 리포트의 §9-3(Runner 제어경로+R5 구현)은 **v2 이후 과제**로 재분류.

*정정 내용은 후속 실측(소스 정독 + pytest/ruff 재실행)에 기반하며, 자식 에이전트 self-report 및 docstring의 "MVP stub" 표기를 맹신하지 않고 Botler가 직접 교차검증한 결과다.*
