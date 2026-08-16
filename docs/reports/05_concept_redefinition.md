# AgentBrowser 개념 재정의서 (v2.0)

- **작성일:** 2026-08-13
- **버전:** v2.0 (개념 재정의 — 기존 설계 문서와 별개의 "정의 기준" 문서)
- **상태:** 검토 기준 초안 (Review Team 이 결(POL)할 기준 문서)
- **작성 근거:** 작업 지시서(사용자 확정 방향: 정체성/정보경로/OOP모듈/리부트방지/재작성범위/개방질문), `IDEA.md`, `.hermes.md`, `docs/reports/01~04`, `docs/progress/01~06` 인용.
- **표기 규칙:**
  - `[사실]` = 인-리포지토리 문서/소스 라인/실행 결과로 검증된 항목.
  - `[권고]` = evidence 기반 권장이나 필수는 아님.
  - `[반대증거]` = 기존 구현·문서와 v2.0 개념이 상충하거나, 미완료·경고인 항목.
- **목적:** 프로젝트가 5회 이상 리부트된 근본 원인(초기 개념 정립 부재 → 오해 누적 → 매번 설계부터 다시)을 차단하기 위한 **단일 개념 기준서**. 이후 모든 설계·구현·리뷰는 본 문서의 정의를 최상위 준거로 삼는다.

---

## 0. 배경 및 작성 동기 — 왜 이 문서가 필요한가

### 0.1 리부트의 근본 원인 (사용자 확정 방향 + 증거)

[사실] 본 프로젝트는 출범 이후 다수의 문서 버전과 구현 반복을 거쳤다. 디스크에 남은 산출물만 보아도 다음과 같이 버전 이력이 중첩되어 있다.

- `docs/reports/01_folder_structure_proposal.md` — v1(2026-08-12) → **v2(2026-08-12)** 로 자체 덮어쓰기. 표기 규칙([사실]/[권고])과 evidence 분리가 v2에서야 도입됨(§6 버전 이력).
- `docs/reports/02_implementation_design.md` — **v1** (요약 설계).
- `docs/reports/03_final_report.md` — **v1** (1~3차 통합 최종). 273행.
- `docs/reports/04_user_manual.md` — **v1**.
- `docs/progress/01~06` — 폴더구조 수용(01), 설계수용(02), CDP 브릿지 구현(03), TDD 원칙(04), 레이트리밋 프로토콜(05), E2E 결과(06)까지 의사결정 로그가 누적.

[사실] 위 산출물 중 `03_final_report.md` §5.1은 **사용자 지적을 직접 인용**으로 기록한다.

> 사용자 지적(Progress doc §8): "CDP 방식 사용해야 하는 것 아닌가? 한계라고 정의해 버리면 어떻게 하라는 거지?"

[사실] 즉, 2차 구현 이전에는 CDP가 '한계/미구현'으로 오개념되어 있었고, 사용자가 이를 "핵심 방식으로 채택하라"고 정정해야 했다(`03_final_report.md` §5.1, `docs/progress/03_cdp_bridge_implementation.md` §근거). 이는 **개념 정립 없이 구현을 진행하다 발생한 오해의 전형**이다.

[권고] "5회 이상 리부트"는 작업 지시서(사용자 확정 방향)가 명시한 프레임이며, 위와 같은 (a)문서 자체버전 덮어쓰기, (b)CDP 오개념 정정, (c)프로파일 공유 금지 지적(`03` §5.2) 등 **개념 단계에서 결론이 안 난 채 구현으로 넘어간 흔적**들이 그 근거로 해석된다. 본 문서는 이 패턴을 끊는 최상위 기준이다.

### 0.2 본 문서의 위계

[사실] `docs/reports/` 는 확정된 **최종 리포트** 보관소이고, `docs/progress/` 는 의사결정 순서·이유 기록소다(`.hermes.md` 컨벤션). 본 문서는 reports에 속하되, **다른 리포트(01~04)보다 상위의 "정의" 문서**로 작성된다. 01~04가 "어떻게 만들었는가"라면 본 문서는 "무엇인가/무엇이 아닌가"를 규정한다.

[권고] 향후 설계 변경은 본 문서 §1~§3 정의를 위배하지 않는 범위에서만 허용한다. 위배가 불가피하면 본 문서를 먼저 개정(버전 bump)한 뒤 설계로 내려간다. 이것이 리부트 방지의 핵심 절차다(§4).

---

## 1. 정체성 (Identity)

> 본 절은 "AgentBrowser가 무엇인가"를 규정한다. 이후 모든 설계는 이 정의에서 파생되어야 한다.

### 1.1 핵심 정의

[사실] `IDEA.md` §1(목적)은 "사용자와 AI 에이전트가 동일한 실제 크롬 브라우징 세션을 공유하는 웹 브라우저" 개발을 목표로 명시한다. `IDEA.md` §2는 비목표(1차)로 "별도 백엔드 서버 운영, 크롬 외 브라우저 지원"을 둔다.

**[사실 — v2.0 정의 1] 독립형 브라우저 도구다. MCP가 아니다. 외부 서버를 운영하지 않는다.**
- MCP(Model Context Protocol)는 외부 클라이언트가 도구를 호출하는 프로토콜 레이어다. AgentBrowser는 그런 서버/프로토콜 노출 물이 아니다.
- [사실] `IDEA.md` §2 비목표 "별도 백엔드 서버 운영"과 정합. `03_final_report.md` §1.3도 "별도 백엔드 서버 없이 로컬 bridge만 사용"으로 경계를 준수했다고 보고함.
- [권고] 따라서 "AgentBrowser를 MCP 서버로 만들자"는 제안은 본 정의와 충돌하므로 채택 불가. 필요하다면 별도 래퍼 프로젝트로 분리하되 본 도구 코어는 변경하지 않는다.

**[사실 — v2.0 정의 2] 이중 사용자 모델(Dual-user model)을 가진다.**
- **인간(Human):** 익스텐션(Content Script / Background) UI로 브라우징하고, 진행 중인 작업을 에이전트에게 넘긴다(핸드오프, `IDEA.md` §3 R3).
- **에이전트(Agent):** CDP / Playwright로 브라우저를 제어한다. 구체적으로 **외부 에이전트가 9222 포트(CDP 진입점)에 붙어** 실제 Chrome 세션을 조작한다.

[사실] 9222 포트는 `launcher.py`가 `--remote-debugging-port=9222`로 기동한 실제(macOS) Chrome의 CDP 진입점이다(`03_final_report.md` §3.1, `04_user_manual.md` §1단계). `cdp_bridge.py:60`의 `connect_over_cdp("http://127.0.0.1:9222")`가 그 증거다.

**[사실 — v2.0 정의 3] 도구는 제어 프로토콜만 제공한다. 두뇌(LLM / Vision)는 외부에 있다.**
- 도구가 하는 일: 세션 기동, DOM/스크린샷/클립보드 추출, 핸드오프 수신, CDP 제어 인터페이스 노출.
- 도구가 하지 않는 일: 추론, 액션 계획 생성, 비전 이해. 이는 외부 에이전트(사용 중인 에이전트 자신)의 책임이다.
- [반대증거] **기존 구현은 이 정의와 충돌한다.** `03_final_report.md` §3.1 흐름도에서 `Runner.run()`이 `_build_prompt()` → `llm.complete(prompt)`(stub) → 액션 계획 텍스트 생성까지 **도구 내부에서 수행**한다(`runner/__init__.py:45-74`). 즉 기존 설계는 "도구 안에 뇌가 있다"고 가정했다. `01_folder_structure_proposal.md` §2도 `src/core/llm/`(LLM 호출·프롬프트·응답 파싱)과 `src/agent/runner/`(에이전트 실행기·상태 관리)를 **내부 모듈**로 배치했다.
- [권고] v2.0은 이 오개념을 시정한다. 기존 `src/core/llm/__init__.py`(LLMClient stub)와 `src/agent/runner/__init__.py`(Runner)는 **"에이전트 연결 지점(AgentController)"으로 재해석**한다. 내장 LLM이 아니라, 외부 에이전트가 플러그인되는 인터페이스다. 재작성 시(§5) 이 모듈들은 `agent_iface` 계층으로 이관하고 내부 추론 로직은 제거한다.

### 1.2 정체성 확장 해석 (명확히 하지 않으면 리부트 유발 지점)

[권고] 아래는 정체성 경계에서 자주 혼동되는 지점을 미리 차단한 것이다.

| 혼동 지점 | v2.0 입장 | 근거 |
|---|---|---|
| AgentBrowser는 "에이전트"인가? | **아니다. 도구(제어 평면)다.** 에이전트는 외부实体. | 정의 3. 내장 LLM 없음. |
| MCP 서버로 확장 가능? | 코어는 아님. 별도 래퍼로만. | 정의 1. |
| 백엔드/클라우드 운영? | 없음. 로컬 전용. | `IDEA.md` §2 비목표. |
| LLM 호출은 어디서? | 외부 에이전트가 담당. stub은 연결점. | 정의 3 + 반대증거 재해석. |
| 헤드리스 모드 지원? | 없음. 헤드풀(화면 있음)만. | `IDEA.md` §3 R1. |

[사실] R1(헤드풀 실제 크롬)은 `IDEA.md` §3에 "헤드리스는 인간 유사 동작·시각적 협업과 모순되어 채택하지 않음"으로 명시됨. `launcher.py`도 macOS 실제 Chrome을 헤드풀 기동(`03_final_report.md` §1.2 R1 매핑).

### 1.3 정체성 검증 체크리스트 (리뷰용)

[권고] 모든 PR/설계안은 아래를 통과해야 한다.
1. 외부 서버/데몬을 새로 띄우지 않는가? (정의 1)
2. 인간·에이전트 이중 경로를 모두 지원하는가? (정의 2)
3. 도구 내부에 LLM 추론/액션 계획 생성 코드가 신규로 들어가지 않는가? (정의 3)
4. CDP 9222 진입점이 외부 에이전트용으로 유지되는가? (정의 2)

---

## 2. 정보 획득 경로 (Information Acquisition Path)

> 본 절은 "도구가 에이전트에게 어떤 정보를, 어떻게 전달하는가"를 규정한다. **쟁점 A/B** 는 사용자 확정 방향에서 이미 결론 난 두 가지다.
> - **쟁점 A (추출 우선순위):** DOM 구조화 JSON 우선 vs 스크린샷 비전 우선 → **DOM 1순위, 스크린샷 폴백**으로 확정.
> - **쟁점 B (세션 주체):** 별도 agent 브라우저 spawn vs 인간 로그인 세션 이어받기 → **실제 Chrome 세션 공유(인간 로그인 프로파일 이어받기) 주 경로**로 확정(봇 탐지 회피 최상).

### 2.1 주 경로: 실제 Chrome 세션 공유 (쟁점 B 확정)

[사실] `03_final_report.md` §5.1은 "AgentBrowser 본질은 인간이 이미 켜둔 헤드풀 크롬 세션을 에이전트가 이어받는 것"이라 명시하고, 새 브라우저 spawn(`launch_headed_chrome`)은 공유 세션이 아니므로 `connect_over_cdp` attach로 교체했음을 보고한다.

**[사실 — v2.0 정보경로 1] 주 경로는 인간이 로그인한 실제 Chrome 프로파일을 에이전트가 CDP로 이어받는 것이다.**
- 인간이 `launcher.py`로 기동한 전용 프로파일(`profiles/<name>`, `--user-data-dir`)에 직접 로그인(`04_user_manual.md` §3단계).
- 에이전트(외부)는 `connect_over_cdp("http://127.0.0.1:9222")`로 그 **동일 탭/세션**에 attach(`cdp_bridge.py:60`, `03_final_report.md` §3.1.1 홉 7).
- [사실] 봇 탐지 회피 측면에서 이 경로가 최상이다. `IDEA.md` §4는 "실제 Chrome 세션 공유"를 핵심 가치로, §3 R2는 헤드풀+인간유사동작으로 봇 탐지 완화를 명시. 이미 인증된 인간 세션을 이어받으면 우회 신호 없이 자연스러운 상태 유지.
- [권고] 부가적으로 CDP 상에서 인간유사 궤적(지터/베지어 곡선 이동)을 주입해 탐지를 더 완화한다. `03_final_report.md` §1.4는 현재 "지터(time.sleep)"만 적용 중이라 보고(반대증거: 베지어 등 정교한 궤적은 미구현). v2.0은 이를 capture/control 계층의 표준 기능으로 격상 권고.

### 2.2 추출: DOM 구조화 JSON 1순위 (쟁점 A 확정)

**[사실 — v2.0 정보경로 2] 추출 1순위는 DOM 추출(구조화 JSON)이다.**
- [사실] `IDEA.md` §3 R4는 "페이지 DOM에서 필요한 콘텐츠를 추출해 구조화하여 저장"을 명시. `03_final_report.md` §1.2 R4 매핑은 `content_script.js`(DOM 캡처) + `tools/__init__.py`의 `parse_dom`(DOM 파싱) 존재를 사실로 보고하나, **영속 저장은 미구현**(반대증거)이라 한다.
- [권고] v2.0은 DOM 추출 결과를 외부 에이전트가 소비 가능한 **구조화 JSON 스키마**로 표준화할 것을 권고. 핸드오프 스키마(`Handoff`: url/dom_snapshot/intent/constraints/timestamp, `handoff.py:21-49`)의 `dom_snapshot` 필드를 그 기반으로 삼는다.

### 2.3 폴백: 도구가 캡처만 하는 경우 (스크린샷 → 외부 비전)

**[사실 — v2.0 정보경로 3] DOM 실패 판단 시 스크린샷 캡처 → PNG를 외부 비전 에이전트에게 위임 분석한다.**
- 도구는 비전 능력이 없다(정의 3). 따라서 DOM으로 구조를 잡을 수 없는 페이지(캔버스·차트·이미지 중심)는 **스크린샷(PNG)만 캡처**하고, 분석은 외부 비전 에이전트(또는 사용 중인 에이전트 자신)에게 넘긴다.
- [권고] 폴백 트리거와 판단 주체는 §6 개방질문으로 남긴다(익스텐션이 판단할지, 에이전트가 판단할지). 본 절은 "무엇을 하는가"만 규정: **도구는 캡처하고, 해석은 외부**가 한다.
- [반대증거] 기존 `runner.run()`은 LLM stub으로 액션 계획을 내부 생성하려 했으나, v2.0 정의 3에 따라 이 responsibility는 외부 에이전트로 이관. 스크린샷 PNG를 에이전트가 직접 CDP로 가져가거나, bridge를 통해 전달하는 채널이 필요.

### 2.4 대안 경로: 클립보드 텍스트 추출

**[사실 — v2.0 정보경로 4] 인간이 Cmd+A / Cmd+C 로 선택·복사한 텍스트는 클립보드에서 도구가 읽어 추출한다.**
- [권고] 이는 DOM 추출이 불가/비효율적인 상황(예: SPA 내부 상태, 드래그 선택 영역)의 가벼운 대안. 도구는 OS 클립보드 읽기 권한 하에 텍스트를 수집해 외부 에이전트에 전달.
- [사실] 이 경로는 `IDEA.md`에 명시되진 않았으나, 사용자 확정 방향(작업 지시)에서 대안 경로로 채택됨. v2.0 정보경로의 한 축으로 편입.

### 2.5 정보경로 요약표

| 경로 | 방법 | 산출물 | 소비자 | v2.0 우선순위 |
|---|---|---|---|---|
| 주 경로 (B) | CDP 세션 공유 | 동일 탭/세션 제어권 | 외부 에이전트 | 최상(봇회피 최상) |
| 추출 (A) | DOM 파싱 | 구조화 JSON | 외부 에이전트 | 1순위 |
| 폴백 | 스크린샷 캡처 | PNG | 외부 비전 에이전트 | DOM 실패 시 |
| 대안 | 클립보드 읽기 | 텍스트 | 외부 에이전트 | 보조 |

[권고] capture 계층(§3)은 이 4갈래를 모두 캡슐화하고, "DOM → 폴백(PNG) → 대안(클립보드)" 순의 전략 체인으로 동작하도록 설계한다.

---

## 3. OOP 모듈 경계 (전략 패턴 / 인터페이스 중심)

> 본 절은 재작성(§5)의 모듈 분할 기준이다. 각 모듈은 **인터페이스(추상 베이스) 중심**으로 설계하고, 구현 교체는 전략 패턴으로 수용한다.

### 3.1 모듈 경계 표 (v2.0 확정)

| 모듈 | 책임 | 추상화 포인트(인터페이스) |
|---|---|---|
| `session` | Chrome 기동 / 프로파일(`profiles/<name>`) / 포트(9222) 관리 | `SessionManager` |
| `capture` | DOM / 스크린샷 / 클립보드 추출 | `CaptureStrategy` (전략 패턴) |
| `bridge` | CS/BG ↔ Python 핸드오프 수신 | `HandoffReceiver` |
| `control` | CDP / Playwright 제어 | `Controller` (인터페이스) |
| `agent_iface` | 외부 에이전트 연결 지점 | `AgentController` (추상) |

### 3.2 모듈별 상세

#### 3.2.1 session — `SessionManager`
[사실] 기존 `launcher.py`가 이 책임을 일부 수행: `--user-data-dir=profiles/<name>` + `--remote-debugging-port=9222` + `--load-extension=src/extension` 기동(`launcher.py:62-76`, `03_final_report.md` §2.2). `--profile` 인자로 프로파일 이름 지정(`04_user_manual.md` §1단계).
[권고] v2.0은 이를 `SessionManager` 인터페이스로 추상화. 기동/종료/포트할당/프로파일생성/pid관리 책임을 캡슐화. `launcher.py`는 이 인터페이스의 구현체로 보존 검토(§5).
[반대증거] `launcher.py:24`는 macOS Chrome 경로를 하드코딩하여 Linux/Windows 기동 불가(`04_user_manual.md` 주의사항 4). `SessionManager`는 OS별 구현을 전략으로 분리 권고(비목표이나 확장 대비).

#### 3.2.2 capture — `CaptureStrategy` (전략 패턴)
[권고] DOM / 스크린샷 / 클립보드 3전략을 `CaptureStrategy` 추상 베이스로 묶고, §2.5의 체인(DOM→PNG→클립보드)을 컨텍스트가 선택하게 한다.
[사실] DOM 추출의 실체는 `content_script.js`(CS 주입) + `tools/__init__.py:parse_dom`(`03_final_report.md` §4.2 단위테스트 `test_parse_dom_valid/invalid`로 검증). 스크린샷은 CDP `Page.captureScreenshot`로 획득 가능(기존 `cdp_bridge` 경로 활용). 클립보드 읽기는 신규(§2.4 대안).
[반대증거] 현재 capture는 CS/BG에 분산되고 Python 측 `parse_dom`만 존재. 통합된 `CaptureStrategy` 체인은 미구현 → 재작성 항목.

#### 3.2.3 bridge — `HandoffReceiver`
[사실] 기존 `bridge_server.py`가 이 책임: `HOST=127.0.0.1`, `PORT=10899` 고정(`bridge_server.py:32-35`), POST `/handoff`·`/hitl` 분기(`bridge_server.py:82-111`), `Handoff.model_validate()`로 pydantic v2 검증(`bridge_server.py:95,100`). E2E에서 `{"status":"ok"}` 수신 확인(`06_e2e_result.md` §5).
[권고] `HandoffReceiver` 인터페이스로 추상화. 수신·검증·외부 에이전트 전달(또는 큐잉)을 책임. 기존 `bridge_server.py`는 구현체로 보존 검토.

#### 3.2.4 control — `Controller` (인터페이스)
[사실] 기존 `cdp_bridge.py`의 `CDPBridge`가 이 책임 일부: `connect_over_cdp("http://127.0.0.1:9222")` attach, 기존 context/page 재사용(동일 탭 제어), `page.goto` + 지터(`cdp_bridge.py:50-66`). `03_final_report.md` §3.1.1 홉 7.
[권고] `Controller` 인터페이스로 추상화하여 CDP 구현체 외에 Playwright 기반 구현체도 교체 가능하게(전략/어댑터). 현재 Playwright 의존성은 테스트/검증용(`04_user_manual.md` §사전준비 3).
[반대증거] `runner.run()`이 CDP를 직접 호출(`runner/__init__.py:79-89`)하여 control 경계를 침범. v2.0은 control 호출을 `agent_iface`/외부 에이전트 책임으로 이관(§1 정의 3).

#### 3.2.5 agent_iface — `AgentController` (추상)
[사실 — v2.0 신규 정의] 외부 에이전트가 도구에 연결되는 지점. 기존 `src/core/llm/`(LLMClient stub)과 `src/agent/runner/`(Runner)를 **이 인터페이스로 재해석**한다(§1.1 정의 3 반대증거).
[권고] `AgentController`는 (a)외부 에이전트가 CDP 9222에 직접 붙는 경로, (b)bridge로 수신된 핸드오프를 외부 에이전트에 전달하는 경로, (c)capture 결과(JSON/PNG/클립보드)를 외부 에이전트에 제공하는 경로를 노출. **내부 추론 코드는 없다.**
[반대증거] 기존 `Runner.run()`의 `_build_prompt()` + `llm.complete()`는 추론이므로 `agent_iface`에서 제거하고, 외부 에이전트가 자신의 LLM으로 수행하도록 한다.

### 3.3 모듈 의존 방향 (의무)

[권고] 의존성은 단방향: `agent_iface` → `bridge`/`capture` → `control`/`session`. 상위 모듈이 하위 인터페이스에 의존하고, 구현은 주입(의존성 주입)한다. 순환 import는 기존처럼 지연 import(`runner/__init__.py:80-81`, `bridge_server.py:25-26`)로 우회하지 말고 인터페이스 분리로 원천 차단.

### 3.4 인터페이스 시그니처 예시 (재작성 설계 기준)

[권고] 아래는 §3.1 의 5개 인터페이스가 가져야 할 핵심 메서드 형태(의사코드, 타입힌트 포함)다. 재작성 시 이 시그니처를 최소 골격으로 삼고, 구현체에서 채운다. `.hermes.md` 개발원칙(OOP 표준·타입힌트·logger 일관성) 준수.

```python
# session — SessionManager
class SessionManager(Protocol):
    def launch(self, profile: str, port: int = 9222) -> "SessionHandle": ...
    def shutdown(self, handle: "SessionHandle") -> None: ...
    def is_alive(self, handle: "SessionHandle") -> bool: ...

# capture — CaptureStrategy (전략 패턴 베이스)
class CaptureStrategy(ABC):
    @abstractmethod
    def capture(self, target: "PageTarget") -> CaptureResult: ...
    # 하위 전략: DomCaptureStrategy / ScreenshotCaptureStrategy / ClipboardCaptureStrategy

# bridge — HandoffReceiver
class HandoffReceiver(Protocol):
    def receive(self, payload: dict) -> Handoff: ...      # pydantic v2 model_validate
    def subscribe(self, agent: "AgentController") -> None: ...

# control — Controller (인터페이스)
class Controller(ABC):
    @abstractmethod
    def attach(self, cdp_url: str) -> None: ...            # connect_over_cdp
    @abstractmethod
    def navigate(self, url: str) -> None: ...
    @abstractmethod
    def act(self, action: "AgentAction") -> "ActionResult": ...

# agent_iface — AgentController (추상, 외부 에이전트 연결점)
class AgentController(ABC):
    @abstractmethod
    def connect(self, session: "SessionHandle") -> None: ...   # 외부 에이전트 진입
    @abstractmethod
    def on_handoff(self, handoff: Handoff) -> None: ...        # bridge 수신 전달
    @abstractmethod
    def provide_capture(self, result: CaptureResult) -> None: ...  # 외부 비전 위임
```

[사실] 위 `SessionManager.launch` 시그니처는 기존 `launcher.py:62-76`(`--user-data-dir=profiles/<name> --remote-debugging-port=9222 --load-extension`)을, `Controller.attach` 는 `cdp_bridge.py:60`(`connect_over_cdp`)을, `HandoffReceiver.receive` 는 `bridge_server.py:95`(`Handoff.model_validate`)을 각각 추상화한 것. 기존 동작 부분을 인터페이스로 올리는 재작성(§5.2)과 정합.
[반대증거] 기존 `Runner.run()`(`runner/__init__.py:45-91`)은 이 인터페이스 중 어디에도 속하지 않는 밀결합 블록(추출→프롬프트→LLM→CDP)이므로, v2.0에서는 `agent_iface`/`control` 경계로 분해·제거된다(§5.3).

---

## 4. 리부트 방지 원칙 (Reboot-Prevention Principles)

> 본 절은 "왜 또 리부트하는가"를 막는 절차적 원칙이다. 위배 시 완료로 보지 않는다.

### 4.1 엄격한 순서: 개념 정립 → 설계 → 원칙/절차 준수

[권고 — 원칙 1] **개념 정립 없이 설계·구현에 진입하지 않는다.** 본 문서 §1~§3이 그 개념 정의다. 새 기능은 이 정의를 먼저 통과시킨 후 설계로 간다.
[사실] 리부트의 근본 원인은 "초기 개념 정립 부재 → 오해 누적"이다(작업 지시/사용자 확정 방향). 증거: §0.1의 CDP 오개념 정정, 문서 자체버전 덮어쓰기.
[권고] 개념과 충돌하는 요구가 들어오면 (1)본 문서 개정 → (2)설계 반영 순으로만 진행. 설계부터 바꾸는 것을 금지.

### 4.2 OOP 채택 이유 (명시)

[권고 — 원칙 2] **OOP를 채택하는 이유는 논리적 분리 + 적극적 모듈화 + 추상화다.** 이는 빠른 개발과 효율적 유지보수를 위한 것이다.
- [사실] `.hermes.md` 개발원칙은 "OOP 표준(캡슐화·타입힌트·logger 일관성, print 디버그 금지)"을 확정(2026-08-13).
- [권고] §3의 인터페이스 중심 설계는 이 원칙의 구체화. 모듈 교체(전략 패턴)가 자유로워야 리부트 없이 진화 가능.
- [반대증거] 기존 구현은 `runner.run()`에 추출→프롬프트→LLM→CDP 제어가 밀결합(`runner/__init__.py:45-91`). 이는 OOP 분리 원칙 위배 → 재작성으로 해소(§5).

### 4.3 확정적 검사 통과 전 완료 금지

[사실 — 원칙 3] `.hermes.md` 개발원칙: "확정적 검사(ruff/pytest/pydantic) 통과 전에는 완료로 보지 않는다." `03_final_report.md` §4는 ruff 0 errors + pytest 13 passed + pydantic 2.13.4로 이 게이트 통과를 사실로 보고.
[권고] v2.0 재작성(§5)에서도 동일 게이트 유지. TDD(실패 테스트 먼저) + ruff 클린 100% + pydantic v2 일원화 + OOP 표준.
[사실] `03_final_report.md` §6.8은 mypy strict 풀패스 여부를 별도 확인 권고로 남김. v2.0도 mypy strict를 게이트에 포함 권고.

### 4.4 리부트 방지 체크리스트 (PR 머지 전)

[권고] 아래 모두 "예"여야 머지.
1. 본 문서 §1 정체성 3원칙 위배 없음?
2. §2 정보경로 4갈래 중 하나 이상 명확히 소속됨?
3. §3 모듈 경계(인터페이스) 준수, 밀결합 없음?
4. TDD/ruff/pydantic/mypy 게이트 통과?
5. 개념과 충돌 시 본 문서부터 개정했는가?

---

## 5. 재작성 범위 (Rewrite Scope — 방식 2: 완전 재작성)

> 사용자 확정 방향은 **방식 2(완전 재작성)** 다. 단, 동작하는 부분은 보존 검토한다.

### 5.1 기본 방침

[사실 — v2.0 재작성 1] **기존 `src/` 전면 재작성**을 원칙으로 한다.
[사실] 기존 테스트 13건(`pytest → 13 passed`, `03_final_report.md` §4.2: unit 10 + integration 3)은 **설계(§3)를 반영한 후 재작성**한다. 기존 테스트는 이전 밀결합 설계에 종속되어 있으므로 그대로 가져가지 않는다.
[권고] 재작성 순서: (1)§3 인터페이스 5종 정의 → (2)각 구현체 TDD 작성 → (3)통합 결선 → (4)게이트 통과. §4 순서 원칙 준수.

### 5.2 보존 검토 대상 ("동작하는 부분")

[사실] 다음은 기존 구현에서 **실제 동작이 검증된 부분**이므로, v2.0 설계(§3)에 부합하면 보존한다.

| 대상 | 검증 근거 | 보존 여부 판단 |
|---|---|---|
| 익스텐션 CS/BG | `06_e2e_result.md` §2 익스텐션 로드 성공, `background.js:15-35` fetch POST 실제 전송 | §3 `bridge`/`capture` 와 정합 시 보존 |
| `launcher.py` | `06_e2e_result.md` §1 Chrome 기동(PID 9430), CDP 응답 성공 | `session`(`SessionManager`) 구현체로 보존 |
| `bridge_server.py` | `06_e2e_result.md` §4~5 기동+수신 `{"status":"ok"}` | `bridge`(`HandoffReceiver`) 구현체로 보존 |
| `cdp_bridge.py` | `03_final_report.md` §3.1.1 홉 7, connect_over_cdp 동일 탭 제어 | `control`(`Controller`) 구현체로 보존 |

[반대증거] 위 4개 중 `runner.run()`이 CDP를 직접 호출하는 부분(`runner/__init__.py:79-89`)은 control 경계 침범이므로 보존 대상에서 **제외**하고 `agent_iface`로 이관(§3.2.5). `src/core/llm/`(LLMClient)은 내장 뇌 오개념이므로 제거/재해석.

### 5.3 제거/재해석 대상

[권고] 아래는 v2.0 정의 3(도구는 뇌 없음)에 따라 정리.
- `src/agent/runner/__init__.py` 의 `_build_prompt()` + `llm.complete()` → 제거. 외부 에이전트 책임.
- `src/core/llm/__init__.py` (LLMClient) → `agent_iface` 의 `AgentController` 연결점으로 재해석, 내부 호출 로직 제거.
- `src/core/orchestrator/__init__.py` 의 runner 위임 흐름 → 외부 에이전트가 CDP/bridge를 직접 쓰므로 오케스트레이션은 최소화하거나 제거.

### 5.4 재작성 완료 기준

[권고] 다음이 충족되어야 재작성 완료로 본다.
1. §3의 5개 인터페이스 모두 구현 + TDD 테스트.
2. ruff 0 errors / pytest 전부 passed / pydantic v2 / mypy strict(권고).
3. E2E: 실제 Chrome 기동 → 익스텐션 → 핸드오프 수신 → 외부 에이전트 CDP 제어(§6.4 한계였던 런타임 연결 실제 성공).
4. 도구 내부에 LLM 추론 코드 0건(정의 3 준수).

### 5.5 구모듈 → 신모듈 마이그레이션 매핑

[권고] 기존 `src/` 산출물을 §3 인터페이스로 어떻게 옮기는지 명시. 보존(§5.2)과 제거/재해석(§5.3)을 한눈에 매핑.

| 기존 모듈/파일 | 기존 책임 | v2.0 대상 | 처리 |
|---|---|---|---|
| `core/launcher.py` | Chrome 기동/프로파일/포트 | `session.SessionManager` | 보존(구현체) |
| `extension/content_script.js` | DOM 캡처 | `capture.DomCaptureStrategy` | 보존(CS 측) |
| `extension/background/background.js` | 메시지 라우팅/전송 | `bridge.HandoffReceiver` + `capture` 트리거 | 보존 |
| `core/bridge_server.py` | 핸드오프 HTTP 수신 | `bridge.HandoffReceiver` | 보존(구현체) |
| `core/cdp_bridge.py` | CDP attach/제어 | `control.Controller` (CDP 구현체) | 보존(구현체) |
| `core/handoff.py` | Handoff/HITL pydantic 스키마 | `bridge` 데이터 모델(유지) | 보존 |
| `core/orchestrator/__init__.py` | runner 위임/상태보유 | `agent_iface` 최소화 또는 제거 | 재해석/축소 |
| `agent/runner/__init__.py` | 프롬프트+LLM+CDP 밀결합 | `agent_iface`(연결점) / `control` 호출 이관 | 제거/분해 |
| `core/llm/__init__.py` | LLMClient stub | `agent_iface.AgentController` 연결점 | 재해석(내부 호출 제거) |
| `agent/tools/__init__.py` | parse_dom/summarize/registry | `capture`/`bridge` 하위 유틸 | 보존(재배치) |

[사실] `handoff.py` 의 `Handoff`/`HITLRequest` pydantic v2 모델(`handoff.py:21-49,51`)은 이미 검증 게이트를 통과한 사실적 자산(`03_final_report.md` §2.1, §4.4)이므로 그대로 유지. `agent/tools` 의 `parse_dom` 은 단위테스트 `test_parse_dom_valid/invalid` 로 검증됨(`03_final_report.md` §4.2) → capture 전략 구현의 기반으로 보존.

---

## 6. 개방 질문 (Review Team 이 답할 항목)

> 아래는 v2.0이刻意 개방해 둔 지점이다. 검토 팀이 결(POL)하여 본 문서에 반영(버전 bump)하기 바란다. 결론 나기 전까지는 [권고] 수준으로 진행.

### 6.1 Q1 — 에이전트 연결 방식
**질문:** 외부 에이전트가 CDP 포트(9222)에 **직접** 붙는가, Python(`agent_iface`)이 **중개**하는가?
- [사실] 현재 양쪽 경로가 혼재되어 있다. `cdp_bridge.py:60`은 CDP 직접 attach 경로이고, `bridge_server.py`(10899)는 Python 중개 경로다(`03_final_report.md` §3.1).
- [권고] v2.0 정의 2는 "외부 에이전트가 9222 포트에 붙음"을 명시하므로 **직접 붙는 경로**를 주로 권장. 단 핸드오프(인간→에이전트) 수신은 Python `HandoffReceiver`(10899)가 중개하는 것이 자연스러우므로, 두 경로를 용도별로 병존시킬 가능성.
- **검토 팀 결정 필요:** (a)CDP 직접 붙음 주력 + bridge는 핸드오프 수신 전용, (b)모든 것은 Python `agent_iface` 가 중개, 둘 중 택일 또는 병존 범위.

### 6.2 Q2 — CaptureStrategy 폴백 트리거 판단 주체
**질문:** DOM 추출 실패 시 스크린샷(PNG) 폴백으로 넘어가는 **판단 주체**는 익스텐션(CS/BG)인가, 외부 에이전트인가?
- [사실] §2.3은 "DOM 실패 판단 시 스크린샷 캡처"만 규정하고 주체를 남김. 기존 `content_script.js`/`background.js` 는 DOM 캡처만 했지 폴백 판단 로직은 없음(`03_final_report.md` §1.2 R4 매핑).
- [권고] 익스텐션이 "DOM 파싱 가능 여부"를 1차 판단(경량)하고, 불가 시 PNG를 캡처해 외부 비전 에이전트에 위임하는 흐름을 제안. 단 외부 에이전트가 직접 CDP 스크린샷을 가져가는 구조라면 주체가 에이전트일 수도 있음.
- **검토 팀 결정 필요:** 폴백 판단을 (a)익스텐션이 담당, (b)외부 에이전트가 담당, (c)양쪽 협의(익스텐션이 플래그만 달고 에이전트가 결정) 중 택일.

### 6.3 Q3 — 프로파일 격리 수준
**질문:** 사용자별 프로파일 관리가 필요한가? 격리 수준은?
- [사실] 현재는 `--profile <name>` 으로 단일 프로파일명 지정(`launcher.py:62`, `04_user_manual.md` §1단계). `profiles/<name>` 은 별도 `user-data-dir`(`03_final_report.md` §5.2). 기본 시스템 크롬과는 절대 공유 안 함(사용자 지적 반영).
- [사실] `02_implementation_design.md` §9/§10 은 `profiles/<name>` 이 수백 MB 점유·로그인 누적되어 **정리 스크립트 필요**를 반대증거로 보고. 현재 정리 유틸 없음(`04_user_manual.md` 주의사항 3).
- [권고] 다중 사용자/다중 작업 격리가 필요하다면 프로파일 레지스트리(이름→경로·만료) 도입 권고. 단 v1(MVP) 범위에서는 단일 `--profile` 로 충분할 수 있음.
- **검토 팀 결정 필요:** (a)단일 `--profile` 유지, (b)사용자별 다중 프로파일 레지스트리 도입, (c)격리 수준(권한 700 적용 여부 — `02` §10 권고 미적용 상태) 택일.

### 6.4 Q4 (파생) — 런타임 E2E 검증 책임
**질문:** §5.4 완료 기준에 든 "런타임 CDP 연결 실제 성공"을 누가·언제 검증하는가?
- [반대증거] `03_final_report.md` §6.2/§6.4 는 "실제 CDP 연결 성공한 적 없음"을 명시적 한계로 보고. `06_e2e_result.md` 는 Chrome 기동·익스텐션·bridge·handoff 수신(HTTP 200)까지만 검증하고, **실제 탭 제어(CDP attach 후 조작)는 미검증**.
- [권고] 재작성 완료 전, 외부 에이전트(또는 테스트 에이전트)가 9222에 붙어 실제 `page.goto`/클릭을 수행하는 E2E 스모크를 필수화할 것을 권고.
- **검토 팀 결정 필요:** 이 E2E 를 (a)재작성 완료 게이트에 포함, (b)별도 후속 과제로 분리 중 탭일.

### 6.5 개방 질문별 선택지 장단점 (검토 참고)

[권고] 각 질문의 선택지별 영향을 미리 정리. 결(POL)은 검토 팀이 본다.

**Q1 (에이전트 연결):**
- (a) CDP 직접 붙음 주력 + bridge는 핸드오프 수신 전용
  - 장: 지연 최소, 외부 에이전트가 세션을 직접 장악(정의 2 충실). 단점: 핸드오프 컨텍스트(의도/제약) 전달은 별도 채널 필요.
- (b) Python `agent_iface` 가 전부 중개
  - 장: 핸드오프·capture·제어를 한 진입점에서 통합. 단점: Python 계층이 상태 보유자 부담(기존 MV3 수명 보완 설계 재현, `03_final_report.md` §1.4).
- (c) 병존(용도별)
  - 장: 실용적. 단점: 경계 문서화 부담. **v2.0 권고안.**

**Q2 (폴백 판단 주체):**
- (a) 익스텐션 1차 판단 → 장: 경량/신속. 단점: CS/BG 에 분기 로직 추가(MV3 제약 주의, `IDEA.md` §6).
- (b) 외부 에이전트 판단 → 장: 도구 단순화(정의 3 일치). 단점: 왕복 지연.
- (c) 익스텐션 플래그 + 에이전트 결정 → 장: 책임 분리 깔끔. 단점: 프로토콜 합의 필요. **v2.0 권고안.**

**Q3 (프로파일 격리):**
- (a) 단일 `--profile` 유지 → 장: 단순. 단점: 다중 작업 혼재.
- (b) 사용자별 다중 레지스트리 → 장: 격리/만료 관리. 단점: 정리 스크립트 필요(`02` §9/§10 반대증거).
- (c) 격리 + 권한 700 → 장: 보안. 단점: 운영 복잡. **권고(보안 강화).**

**Q4 (E2E 검증 책임):**
- (a) 완료 게이트 포함 → 장: 리부트 방지 확실. 단점: 재작성 종료 지연. **v2.0 권고안.**
- (b) 후속 과제 분리 → 장: 빠른 골격. 단점: 미검증 상태 잔존(§6.4 반대증거 반복 위험).

---

## 7. 요약 — v2.0이 리부트를 막는 메커니즘

[사실] 본 문서는 다음 3축으로 리부트를 차단한다.
1. **정의 우위(§1):** 도구=제어평면, 뇌=외부. 이 경계를 위배하는 제안(내장 LLM, MCP 서버, 백엔드)을 사전 차단. 기존 `runner`/`llm` 의 오개념을 명시적으로 재해석.
2. **정보경로 표준화(§2):** 쟁점 A/B(추출우선순위·세션주체)를 확정하여 "어떻게 정보를 얻나" 논의를 종결.
3. **OOP 모듈 경계 + 리부트 방지 절차(§3~§4):** 인터페이스 중심 분리로 교체 자유, 게이트 통과 전 완료 금지로 품질 확보.

[권고] 본 문서가 "최상위 준거"로 작동하려면, 이후 모든 설계안/PR이 §4.4 체크리스트를 통과해야 한다. 개념과 충돌하는 변경은 본 문서 개정(버전 bump)을 먼저 거치게 하여, "구현부터 다시" 패턴을 끊는다.

---

## 부록 A: 증거 출처 일람 (Analyst R01 — source 명시)

- **`IDEA.md`** §1(목적)·§2(범위/비목표)·§3(R1~R5)·§4(구현경로/책임분리)·§6(리스크) — 정체성·정보경로·봇회피 책임 분리의 1차 근거.
- **`.hermes.md`** — 컨벤션, 개발원칙(TDD/ruff/pydantic v2/OOP), "확정적 검사 통과 전 완료 금지".
- **`docs/reports/01_folder_structure_proposal.md`** §2(트리)·§4(evidence)·§6(버전이력 v1→v2) — 기존 문서 자체 버전 덮어쓰기 증거, `src/core/llm`·`src/agent/runner` 내부 배치 사실.
- **`docs/reports/02_implementation_design.md`** §9/§10 — 별도 프로파일 원칙, `profiles/<name>` 디스크 점유 경고, CDP 브릿지 아키텍처.
- **`docs/reports/03_final_report.md`** §1.1~§1.4(본질/요구매핑/설계철학)·§2(구현산출물)·§3(아키텍처/홉추적)·§4(품질검증)·§5(사용자지적)·§6(한계) — 런처/CDP/bridge 라인 인용, LLM stub·E2E 미검증·MV3 수명 등 반대증거.
- **`docs/reports/04_user_manual.md`** §0~§문제해결·주의사항 — 실제 사용 흐름, 9222/10899 포트, 프로파일 격리, macOS 전용, LLM stub 한계.
- **`docs/progress/03_cdp_bridge_implementation.md`** — 사용자 지적 직접 인용("CDP 한계 정의 말 것", "프로파일 공유 금지").
- **`docs/progress/06_e2e_result.md`** — Chrome 기동(PID 9430)·익스텐션 로드·CDP 응답·bridge 수신(`{"status":"ok"}`) E2E 부분 검증. 실제 탭 제어는 미검증.
- **소스 라인 인용:** `launcher.py:24,62-76`, `bridge_server.py:32-35,82-111`, `cdp_bridge.py:50-66`, `background.js:15-35`, `runner/__init__.py:45-91`, `handoff.py:21-49`, `manifest.json:8-9`, `pyproject.toml`, `.gitignore:34`.

## 부록 B: 버전 이력

- **v2.0 (2026-08-13):** 개념 재정의서 최초 작성. 정체성(독립형/이중사용자/제어평면만)·정보경로(쟁점 A/B 확정)·OOP 모듈 경계(5인터페이스)·리부트 방지 원칙·완전 재작성 범위·개방질문 3(+파생1) 수록. 기존 01~04 리포트와 `IDEA.md`/`.hermes.md`/progress 를 증거로 인용. `[사실]`/`[권고]`/`[반대증거]` 표기 적용. 400~600줄 분량.

## 부록 C: 타 문서와의 관계

- **상위:** 본 문서(05) — 개념 정의 기준.
- **하위:** `01`(폴더구조)·`02`(설계)·`03`(최종보고)·`04`(매뉴얼) — 본 정의를 따르는 산출물. 충돌 시 본 문서 우선.
- **갈등 지점 (명시):** `01`/`03` 이 `src/core/llm`·`src/agent/runner` 를 내부 모듈로 둔 것은 v2.0 §1.1 정의 3(도구는 뇌 없음)과 충돌 → v2.0 우선, 해당 모듈은 `agent_iface` 로 재해석(§5.3).
