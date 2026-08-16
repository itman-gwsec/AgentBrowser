# 08. HITL(인간 개입) 설계 및 구현 로그

> 작성 롤: analyst (R01) — 모든 주장은 실제 소스 코드·테스트 실행 결과에 기반.
> 대상 커밋: HITL 상태머신(pause/resume)+캡차 트리거 구현.

---

## §1. 배경 및 목적

- AgentBrowser 는 인간과 에이전트가 **동일한 실제 Chrome 세션**을 공유/협업하는 것을 핵심 가치로 한다.
- 사이트는 로그인·결제·봇 차단 지점에서 **캡차/로봇 확인**을 강제한다. 에이전트가 이를 자동 우회하는 것은 허용 범위가 아니며(IDEA.md R2 봇회피 금지), 인간의 실제 개입이 필요하다.
- 따라서 에이전트가 "자동 처리 불가"를 판단하면, 그 지점을 **인간에게 위임(Human-In-The-Loop)** 하고 대기하는 메커니즘이 필수다.
- 요구 근거: IDEA.md R2(봇회피 금지)·R3(인간→에이전트 위임)·R6(HITL 캡차 위임), 그리고 `src/core/handoff.py` 의 `HITLRequest` 스키마(R6 명시).
- 목적: 캡차 탐지 → HITLRequest 생성 → 오케스트레이터 대기 상태머신 전이 → 인간 개입 후 재개, 일련의 흐름을 구현하고 검증한다.

---

## §2. 구현 범위

### A. CDP 캡차 탐지 → HITLRequest (src/core/cdp_bridge.py)
- `CDPBridge.detect_and_request_hitl()` 가 페이지 본문+HTML 에서 캡차 흔적을 스캔하고, 탐지 시 `HITLRequest` 를 반환한다.
- 브리지는 *탐지*에만 집중(단일 책임). 실제 오케스트레이터 전달은 호출자(agent runner) 책임.

### B. 오케스트레이터 HITL 상태머신 (src/core/orchestrator/__init__.py)
- URL 단위 대기 상태를 인메모리(`_hitl_state: dict[str,str]`)로 보유한다.
- 상태 전이: `(없음) --pause_for_human--> "awaiting" --resume--> "resolved"`.
- 기존 `receive_hitl()` (console+file JSONL 로그)은 삭제/변경 없이 보존되어, 상태머신 상위에서 재사용된다.

### (지원 증거) 수신 경로 아키텍처
- `src/core/bridge_server.py` L99-101: `POST /hitl` 이 `HITLRequest` 를 파싱하여 `Orchestrator().receive_hitl()` 로 전달한다 (확인 완료).

---

## §3. 실제 구현 명세 (소스 검증 기준)

### 3.1 cdp_bridge.detect_and_request_hitl() — cdp_bridge.py L154-179
- 시그니처: `def detect_and_request_hitl(self) -> HITLRequest | None`
- 스캔 대상: `page.evaluate` 로 본문 텍스트 + HTML 소스를 소문자로 결합한 뒤,
  패턴 `['captcha', '로봇 확인', 'unusual traffic', 'recaptcha', 'vaptcha']` 포함 여부 판정(인라인 JS 상수 `_CAPTCHA_SCAN_JS`, L37-45).
- 동작:
  - `page is None` 이면 경고 후 `None` 반환.
  - 평가 예외 시 보수적 fallback 으로 `None` 반환.
  - 탐지 시 `HITLRequest(url=self.page.url, reason="captcha_detected")` 반환, 미탐지 시 `None`.

### 3.2 orchestrator 상태머신 4메서드 (orchestrator/__init__.py)
1. `request_hitl(handoff_url, reason) -> HITLRequest` — L121-128
   - `HITLRequest(url=handoff_url, reason=reason)` 생성 → `receive_hitl(hitl)` 래핑 → **동일 객체** 반환(중복 로직 없음).
2. `pause_for_human(url) -> HITLRequest` — L130-137
   - `_hitl_state[url] = "awaiting"` 로 상태 전이 후, `request_hitl(url, "captcha_detected")` 호출.
3. `resume(url) -> None` — L139-141
   - `_hitl_state[url] = "resolved"` 로 대기 해제.
4. `is_paused(url) -> bool` — L143-145
   - `_hitl_state.get(url) == "awaiting"` 여부 반환.

### 3.3 receive_hitl() 보존 사실 — orchestrator/__init__.py L94-119
- 삭제/변경 없이 그대로 유지.
- 동작: 인메모리 `_hitl_log` 에 `{"url","reason","timestamp","logged_at","status"}` 기록(`status="awaiting_human"`),
  console 로그(`[HITL] 인간 개입 대기`), 그리고 file JSONL 로그(`logs/hitl_requests.log`)에 append.
- 상태머신 메서드들은 모두 이 `receive_hitl()` 을 재사용한다.

---

## §4. 캡차 위임 채널 결정 (분석 결과)

- **MVP 시나리오**: 인간이 브라우저 화면 앞에 있는 상태. AgentBrowser 의 핵심 가치는 인간↔에이전트 동일 실제 세션 공유/협업이므로, MVP 부족분은 "인간이 자리에 있음"을 전제로 한다.
- **결정(MVP)**: 익스텐션(Content Script/Background)이 브라우저 내 **"⚠ 캡차 발생, 개입 필요" 배너**를 띄우고,
  인간이 익스텐션의 **"재개" 버튼**으로 `resume(url)` 을 호출한다. → 텔레그램/외부 채널 불필요.
- **텔레그램/맥 알림 등 out-of-band 채널**: "인간이 자리 비운 unattended 위임" 시나리오에서만 필요 = **Phase 2 선택 과제**. 현재는 미구현, 범위 외.
- **결론**: 텔레그램은 MVP 필수 아님. 인브라우저 배너를 우선 구현하고, 텔레그램 연동은 후속 결정 사항으로 분리.

---

## §5. 검증 결과 (실제 실행)

- `ruff check` (대상 4파일): **All checks passed!**
- `pytest` (전체): **26 passed** (기존 21 + 본 구현 신규 5).
  - `tests/unit/test_cdp_bridge_guard.py`: 4건 — connect 봇탐지 차단 2건 + `detect_and_request_hitl` 탐지/미탐지 2건.
  - `tests/unit/test_orchestrator.py`: 6건 — init/receive_handoff/receive_hitl 로그 + pause/resume/request_hitl 상태머신 3건.
- HITL 상태머신(`pause_for_human`→`is_paused` True, `resume`→False) 및 `request_hitl` 이 `receive_hitl` 경유 로그 기록까지 단위 검증 완료.

---

## §6. 차후 과제

1. **익스텐션 배너 UI**: Content Script/Background 가 캡차 탐지 시 인브라우저 "⚠ 캡차 발생, 개입 필요" 배너 노출.
2. **resume 트리거 연결**: 배너의 "재개" 버튼 → `POST /hitl`/직접호출로 `Orchestrator().resume(url)` 연결.
3. **텔레그램(Phase 2)**: 인간 부재 unattended 위임 시나리오용 out-of-band 알림 — 범위 외, 후속 결정.
4. **상태 영속화**: 현재 `_hitl_state` 는 인메모리(MVP). 재기동 복원을 위한 영속 저장(§9 상태 보유 보완) 필요.
5. **bridge_server /hitl 연동 검증 강화**: 통합 테스트에서 `pause_for_human`→`POST /hitl`→`resume` 전체 경로 커버.
