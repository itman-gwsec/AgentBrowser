# 최종 보고서 (AgentBrowser MVP + CDP 브릿지 + 품질확보)

- **작성일:** 2026-08-13
- **프로젝트:** AgentBrowser (`/Volumes/Data_Vault/ExoCortex/Projects/AgentBrowser/`)
- **버전:** v1 (1차 MVP + 2차 CDP 브릿지 + 3차 품질확보 통합 최종)
- **표기 규칙:** `[사실]` = 디스크/실행 결과/소스 라인 인용으로 검증된 항목. `[권고]` = evidence 기반 권장(필수 아님). `[반대증거]` = 상충하는 사실·미완료·경고.
- **검증 방법:** 2026-08-13 기준, `source .venv/bin/activate` 후 `ruff check src tests`, `pytest -q`, `python -c "import pydantic"` 실제 실행 + `find`/`grep` 디스크 실측 + 소스 라인 직접 인용. 임의 추측은 배제함.

---

## 1. 개요 및 목표

### 1.1 프로젝트 본질
[사실] `IDEA.md` §1(목적)은 "사용자와 AI 에이전트가 동일한 실제 크롬 브라우징 세션을 공유하는 웹 브라우저" 개발을 목표로 명시한다. 인간이 직접 시작한 웹 작업(검색·조회·자동화)을 에이전트가 이어받아 수행하고, 필요 시 다시 인간에게 넘기는 **협업형 브라우징(인간-에이전트 핸드오프)** 이 핵심 가치이다. 기존 자동화 도구(Playwright/Puppeteer/MCP)는 공유 세션·실시간 협업 UI를 제공하지 않으므로 이를 차별점으로 삼는다(`IDEA.md` §4).

### 1.2 핵심 요구사항 (IDEA.md §3, R1~R5)
[사실] 구현의 평가 기준은 `IDEA.md` §3의 5개 요구사항이다. 본 프로젝트의 1~3차 산출물은 이를 사실 기반으로 다음과 같이 매핑한다.

| 요구사항 | 내용 (IDEA.md §3 직접 인용 요지) | 본 구현 반영 상태 |
|---|---|---|
| **R1** | 헤드풀(headed) 실제 크롬. 헤드리스는 인간 유사 동작·시각적 협업과 모순되어 채택 안 함. | [사실] `launcher.py`가 macOS 실제 Chrome을 `--remote-debugging-port=9222 --load-extension=src/extension`로 헤드풀 기동(`launcher.py:23-24, 69-76`). |
| **R2** | 봇 탐지 회피 + 캡차 인간 위임(HITL). 헤드풀+인간유사동작(타이밍·궤적). 캡차 등은 즉시 인간 위임. | [사실] 회피는 헤드풀+지터(타이밍)로 담당, 익스텐션은 회피 목적 사용 안 함(`runner/__init__.py:29-31`, `background.js:87-88`). HITL 라우팅은 `background.js` HITL case + `orchestrator.receive_hitl()` 로그 기록으로 일부 반영. |
| **R3** | 인간→에이전트 위임/핸드오프. 위임 시 URL·DOM 스냅샷·의도·제약 함께 전달. | [사실] `handoff.py`의 `Handoff` pydantic 모델(url/dom_snapshot/intent/constraints/timestamp)로 스키마 확정(`handoff.py:24-49`). 전송 경로(CS→BG→bridge→Orchestrator→Runner) 구현 완료. |
| **R4** | DOM 추출·저장. 페이지 DOM에서 콘텐츠 추출해 구조화 저장. | [사실] `content_script.js`(DOM 캡처용) + `background.js` 인메모리 `handoffs[]` 구조(`background.js:8`) 존재. 단 영속 저장은 미구현(후속). |
| **R5** | 분할 화면 협업. 사용자와 에이전트가 같은 세션을 함께 봄. | [반대증거] 분할 화면 UI는 `IDEA.md` §2 후속 범위로 명시되어 있으며 v1에서 미구현. 핸드오프 contract만 우선 확정. |

[사실] 위 5개 요구사항 중 R1·R3는 런타임 전제 없이 코드 레벨로 검증 완료(런처 플래그, 핸드오프 스키마+전송 경로). R2는 "회피 설계 원칙 + HITL 라우팅"까지만 반영되었고, 캡차 실제 중단/재개는 미구현(§6.6). R4는 DOM 파싱 도구(`parse_dom`)와 인메모리 저장까지만이며 영속 저장 미구현(§6.5). R5는 v1 범위 외. 즉 **"인간→에이전트 위임 1종"(MVP 경계, `IDEA.md` §2)은 핵심 경로 기준 충족**이나, 위임의 종단(실제 브라우저 제어·영속·협업 UI)은 후속으로 열려 있다.

### 1.4 설계 철학 (사실 기반 원칙)
[사실] 구현 전반에 일관 적용된 3원칙은 소스/doc에 명시되어 있다.
- **회피 금지 원칙:** 익스텐션을 봇 회피/캡차 우회에 사용하지 않음. 회피는 헤드풀 브라우저 자체 동작(지터)에 위임(`background.js:87-88`, `runner/__init__.py:7-12`, `bridge_server.py:11`). 이는 `IDEA.md` §4 책임 분리와 정합.
- **상태 보유자 원칙:** MV3 SW 수명 제약 보완을 위해 Python bridge(`Orchestrator`)가 수신 큐/HITL 로그를 인메모리 보유(`orchestrator/__init__.py:62-67`, §9).
- **지연 연결/지연 import 원칙:** CDP는 `connect()` 호출 전 미접속(`cdp_bridge.py:33,50`), core↔agent 순환 import는 지연 import로 방지(`runner/__init__.py:80-81`, `bridge_server.py:25-26`).

### 1.3 MVP 경계
[사실] `IDEA.md` §2는 MVP 경계를 "헤드풀 실제 크롬 브라우징, DOM 추출·저장, 인간→에이전트 위임 시나리오 1종"으로 한정하고, 비목표로 "별도 백엔드 서버 운영, 크롬 외 브라우저 지원"을 둔다(`IDEA.md` §2). 본 구현은 이 경계를 준수했다(별도 백엔드 서버 없이 로컬 bridge만 사용).

---

## 2. 구현 결과

### 2.1 1차 MVP 산출물
[사실] 디스크 실측(`find`)으로 확인된 파일 목록과 역할.

| 파일명 | 역할 | 검증 결과 |
|---|---|---|
| `src/extension/background/background.js` | MV3 Service Worker. 메시지 라우터(HANDOFF/HITL/GET_HANDOFFS) + 인메모리 저장소 + Python bridge 전송(`fetch` POST). | [사실] 88행, `forwardToAgent()`/`sendHITL()`로 `http://127.0.0.1:10899` 전송(`background.js:15-35`). 회피 로직 일절 없음(`background.js:87-88`). |
| `src/extension/content_script/content_script.js` | Content Script. 페이지 DOM·상호작용 캡처(CS↔BG `chrome.runtime` 메시징). | [사실] 디스크 존재 확인(`src/extension/content_script/content_script.js`). MVP stub 수준. |
| `config/manifest.json` | MV3 매니페스트. `background.service_worker`, `content_scripts` 경로 정의. | [사실] `background/background.js`, `content_script/content_script.js` 경로 지정(`manifest.json:8-9`). |
| `src/core/handoff.py` | R3 핸드오프/HITL pydantic v2 스키마. | [사실] `Handoff`/`HITLRequest` `BaseModel`(`handoff.py:21-49, 51`). `model_validate`로 bridge 수신 단계 검증(`bridge_server.py:95,100`). |
| `src/core/browser/__init__.py` | 브라우저 제어 계층(Stub). | [사실] 디스크 존재. 실제 제어는 후속(~cdp_bridge로 일부 이관). |
| `src/core/llm/__init__.py` | LLM 클라이언트(env 기반 stub). | [사실] `Runner`가 `LLMClient()` 호출(`runner/__init__.py:43`). 실제 호출은 미수행(stub). |
| `src/core/orchestrator/__init__.py` | 핸드오프/HITL 수신 및 runner 위임 진입점(§9 Python bridge 상태 보유자). | [사실] `receive_handoff()`→`runner.run()` 위임, `receive_hitl()` 로그 기록(`orchestrator/__init__.py:69-115`). |
| `src/agent/tools/__init__.py` | 에이전트 도구 계층(Stub). | [사실] 디스크 존재 + `tests/unit/test_tools.py`(4건)로 검증. |
| `src/agent/runner/__init__.py` | Handoff→LLM→액션 계획. CDP 결선 포함. | [사실] `run()`이 프롬프트 조립→지터→`llm.complete()`→CDP 제어 부가(`runner/__init__.py:45-91`). |

### 2.2 2차 CDP 브릿지 산출물
[사실] 사용자 지적(§5) 반영을 위해 1차의 "브릿지 미구현/stub"를 CDP 기반 실제 브릿지로 교체.

| 파일명 | 역할 | 검증 결과 |
|---|---|---|
| `src/core/launcher.py` | 별도 프로파일 + 디버그 포트 + 익스텐션 기동. | [사실] `--user-data-dir=profiles/<name>` + `--remote-debugging-port=9222` + `--load-extension=src/extension`(`launcher.py:62-76`). 기본 프로파일 공유 금지 설계(`launcher.py:4-12`). |
| `src/core/bridge_server.py` | 익스텐션→Python 핸드오프 수신 HTTP 서버. | [사실] `PORT=10899`, `HOST=127.0.0.1` 고정(`bridge_server.py:32-35`). POST `/handoff`,`/hitl` 분기(`bridge_server.py:82-111`). 표준 라이브러리만 사용. |
| `src/core/cdp_bridge.py` | 실행 중 크롬에 CDP attach(동일 탭 제어). | [사실] `connect_over_cdp("http://127.0.0.1:9222")`(`cdp_bridge.py:60`). 기존 context/page 재사용(익스텐션 탭 보존, `cdp_bridge.py:62-66`). 지연 연결(`connect()` 호출 전 미접속). |
| `src/extension/background/background.js` (보강) | `fetch POST :10899` 실제 전송 추가. | [사실] 1차 대비 전송 로직 확정(`background.js:15-35`). |
| `src/core/orchestrator/__init__.py` (보강) | CDPBridge 연동. | [사실] `self.cdp: CDPBridge | None = None` 보유(`orchestrator/__init__.py:60`); 실제 CDP 제어는 runner가 담당(중복 제거). |
| `.gitignore` | `profiles/` 커밋 제외. | [사실] `# AgentBrowser 전용 크롬 프로파일 ... profiles/` 추가(`.gitignore:34` 라인 인용 확인). |
| `docs/reports/02_implementation_design.md` §10 | CDP 브릿지 아키텍처 보강. | [사실] §10 "CDP 브릿지 아키텍처" 6문단 추가(`02_implementation_design.md:46-56`), 파일:라인 인용 포함. |

### 2.3 3차 품질확보 산출물
[사실] 정적/동적 품질 게이트 도입.

| 항목 | 산출물 | 검증 결과 |
|---|---|---|
| 린트 설정 | `pyproject.toml` `[tool.ruff.lint]` strict select(`E,F,I,B,UP,RUF,TRY,DTZ,C4,SIM,PL`), `ignore=[]`. | [사실] `pyproject.toml:12-31`. `BLE001`만 의도적 안전 fallback으로 `extend-ignore`. |
| 테스트 설정 | `[tool.pytest.ini_options]` `pythonpath=["src"]`, `testpaths=["tests"]`. | [사실] `pyproject.toml:37-41`. |
| 타입 설정 | `[tool.mypy]` `strict=true`. | [사실] `pyproject.toml:43-47`. |
| 린트 실행 | `ruff check src tests`. | [사실] `ruff 0.16.2` → **"All checks passed!"** (0 errors). |
| 테스트 실행 | `pytest -q`. | [사실] **13 passed in 1.07s**. unit 10(test_handoff 3 + test_orchestrator 3 + test_tools 4) + integration 3(test_bridge_server 2 + test_launcher 1). |
| OOP 정리 | `print`→`logger` 전환. | [사실] `src/` 내 `print(` 잔여 **0건**(grep 실측). 4건 전환 주장과 정합. 로거는 19곳 사용(`src/` grep `logger` 19건). |
| 경로 수정 | `manifest.json` 익스텐션 경로. | [사실] `background/background.js`, `content_script/content_script.js`로 상대 경로 정정(`manifest.json:8-9`). |
| CDP 결선 | `runner.run()` 내부 CDP 호출. | [사실] `runner/__init__.py:79-89`에서 `CDPBridge()` import→`connect()`→`control()` 부가 수행, 실패 시 안전 fallback(결과만 반환). |
| 의존성 일원화 | pydantic v2. | [사실] `pydantic 2.13.4`. `BaseModel`/`Field`/`model_validate` 일관 사용(`handoff.py`, `bridge_server.py`). |

---

## 3. 아키텍처

### 3.1 전체 흐름 (사실 기반)
[사실] 요청된 흐름 `CS → BG → bridge:10899 → Orchestrator → Runner + CDPBridge:9222`는 소스 라인으로 확인된다.

```
[크롬 익스텐션 (MV3)]
  Content Script (content_script.js)
    │  chrome.runtime.sendMessage({type:"HANDOFF", payload:{url,dom_snapshot,intent,constraints}})
    ▼
  Background Service Worker (background.js)
    │  forwardToAgent() → fetch POST http://127.0.0.1:10899/handoff   (background.js:15-24)
    ▼
[Python core — 로컬 bridge]
  bridge_server.py  (ThreadingHTTPServer, HOST=127.0.0.1, PORT=10899)
    │  do_POST() → Handoff.model_validate(payload) → Orchestrator().receive_handoff()
    │                                              (bridge_server.py:82-102)
    ▼
  Orchestrator.receive_handoff()  (orchestrator/__init__.py:69-88)
    │  _handoff_queue.append(handoff)  →  runner.run(handoff)
    ▼
  Runner.run()  (runner/__init__.py:45-91)
    │  1) _build_prompt(handoff)  →  2) 지터(time.sleep)  →  3) llm.complete(prompt)
    │  └─ [CDP 결선] CDPBridge().connect() → control(handoff)
    ▼                                          ▼
  LLM 액션 계획 텍스트 반환            CDPBridge (cdp_bridge.py)
                                            connect_over_cdp("http://127.0.0.1:9222")  (cdp_bridge.py:60)
                                            → 기존 context/page 재사용(동일 탭 제어)
                                            → page.goto(handoff.url) + 지터

[런처] launcher.py: macOS Chrome 헤드풀 기동
   --user-data-dir=profiles/<name>  --remote-debugging-port=9222  --load-extension=src/extension
   (launcher.py:62-76)  →  포트 9222가 CDP 진입점, profiles/ 가 별도 세션 저장소
```

### 3.1.1 홉별 추적 (사실 기반 라인 인용)
[사실] 위 흐름의 각 홉을 소스 라인으로 추적하면 다음과 같다.

1. **홉 1 (CS → BG):** `content_script.js`가 `chrome.runtime.sendMessage({type:"HANDOFF", payload})` 전송 → `background.js:39-59`의 `onMessage` 라우터가 `handoffs.push()` 후 `forwardToAgent()` 호출.
2. **홉 2 (BG → bridge):** `background.js:17-23` `fetch("http://127.0.0.1:10899/handoff", POST)`로 실제 전송. CORS 무관(MV3 SW 자체 fetch, `background.js:13` 주석).
3. **홉 3 (bridge 수신 → Orchestrator):** `bridge_server.py:82-97` `do_POST()`가 `/handoff` 분기 → `Handoff.model_validate(payload)`(pydantic v2 검증) → `Orchestrator().receive_handoff(handoff)` 위임.
4. **홉 4 (Orchestrator → Runner):** `orchestrator/__init__.py:69-88` `receive_handoff()`가 `_handoff_queue.append()` 후 `runner.run(handoff)` 위임, runner 부재 시 `RunnerUnavailableError` 발생(안전 경계).
5. **홉 5 (Runner 내부):** `runner/__init__.py:45-74` `_build_prompt()` → 지터(`time.sleep`) → `llm.complete(prompt)`(stub)로 액션 계획 텍스트 생성.
6. **홉 6 (Runner → CDPBridge):** `runner/__init__.py:79-89` 지연 import `CDPBridge` → `connect()` → `control(handoff)`. 실패 시 `logger.warning` 후 LLM 결과만 반환(안전 fallback).
7. **홉 7 (CDPBridge → 실제 Chrome):** `cdp_bridge.py:50-66` `sync_playwright().chromium.connect_over_cdp("http://127.0.0.1:9222")`로 기동 중 탭 attach, 기존 context/page 재사용(동일 탭), `page.goto(handoff.url)` + 지터.

### 3.2 경계와 책임 분리
[사실] `02_implementation_design.md` §2는 3경계(CS / Background / Python core·agent)를 규정한다. 본 구현은 이를 충실히 따른다:
- CS↔Background: `chrome.runtime` 메시징(`background.js:39-85`).
- Background↔Python: 로컬 HTTP bridge(:10899)로 격리(`bridge_server.py`, `background.js:17`).
- Python bridge가 세션 상태(수신 큐/HITL 로그)를 인메모리 보유하여 MV3 SW 수명 제약(§9)을 보완(`orchestrator/__init__.py:62-67`).
- 회피 책임은 익스텐션이 아닌 헤드풀 브라우저 자체(지터)에 위임(`runner/__init__.py:29-31`, `background.js:87-88`).

### 3.3 보안 설계
[사실] `bridge_server.py`는 bind host를 `127.0.0.1`로 고정해 외부 노출을 차단한다(`bridge_server.py:35`). `profiles/`는 `.gitignore` 대상으로 커밋 누수를 막는다(`.gitignore:34`).

---

## 4. 품질 검증

### 4.1 정적 분석 (Ruff)
[사실] 2026-08-13 실행 결과:
```
$ ruff check src tests
All checks passed!
$ ruff --version
ruff 0.16.2
```
- 선택 규칙: `E, F, I, B, UP, RUF, TRY, DTZ, C4, SIM, PL`(pycodestyle/Pyflakes/isort/bugbear/pyupgrade/ruff/tryceratops/datetimez/comprehensions/simplify/pylint) — `pyproject.toml:14-26`.
- `ignore = []`(무시 규칙 없음), `BLE001`만 의도적 안전 fallback으로 `extend-ignore`(`pyproject.toml:28-31`).
- **결과: 0 errors** (에러 0 목표 달성).

### 4.2 동적 분석 (Pytest, TDD)
[사실] 2026-08-13 실행 결과:
```
$ pytest -q
.............                                           [100%]
13 passed in 1.07s
```
테스트 분포(실측 `grep -c "def test_"`):
- **unit 10건**: `test_handoff.py`(3) + `test_orchestrator.py`(3) + `test_tools.py`(4).
- **integration 3건**: `test_bridge_server.py`(2) + `test_launcher.py`(1).
- **합계 13건, 전부 passed.**

[사실] 13건의 실제 테스트 함수명(디스크 `grep -rh "def test_"` 실측):

| 계층 | 파일 | 테스트 함수 (실측) |
|---|---|---|
| unit | `test_handoff.py` | `test_required_field`, `test_defaults`, `test_hitl` |
| unit | `test_orchestrator.py` | `test_init`, `test_receive_handoff_no_runner`, `test_receive_hitl_log` |
| unit | `test_tools.py` | `test_parse_dom_valid`, `test_parse_dom_invalid`, `test_summarize`, `test_registry` |
| integration | `test_bridge_server.py` | `test_handoff_endpoint`, `test_invalid_json` |
| integration | `test_launcher.py` | `test_args_construction` |

- [사실] 단위 테스트는 pydantic 스키마 검증(`test_required_field`/`test_defaults`/`test_hitl`), 오케스트레이터 위임/폴백(`test_init`/`test_receive_handoff_no_runner`/`test_receive_hitl_log`), 도구 계층 파싱·요약·레지스트리(`test_parse_dom_*`/`test_summarize`/`test_registry`)를 커버한다. `tools/__init__.py`는 `parse_dom`(R4 DOM 파싱), `summarize_handoff`(R3 요약), `ToolRegistry`(디스패처) 3책임을 가진다(소스 헤더 인용).
- [사실] 통합 테스트는 `bridge_server` 픽스처를 띄워 `/handoff` 정상 수신(`test_handoff_endpoint`)과 잘못된 JSON 거부(`test_invalid_json`)를, `launcher`는 인자 조합 생성(`test_args_construction`)을 검증한다. pytest `monkeypatch`/`fixture` 활용(실측 시그니처 확인).

[사실] TDD 적용: `docs/progress/04_dev_principles_tdd.md`에 TDD 원칙 문서화, RED-GREEN 패턴으로 테스트 우선 작성 후 구현 결선. `tests/`는 `unit/`·`integration/` 2계층으로 매핑(`02_implementation_design.md` §8 관행 준용, `pyproject.toml:37-41` pythonpath 설정).

### 4.3 타입 검증 (Mypy)
[사실] `[tool.mypy] strict = true` 설정(`pyproject.toml:43-47`). OOP 타입 검증을 위한 strict 모드 활성화. (실행은 3차 게이트에 포함되나 본 보고서 작성 시점 mypy `strict` 풀패스는 별도 확인 권장 — 아래 §6 한계 참조.)

### 4.4 의존성 품질
[사실] pydantic **2.13.4**로 v2 일원화. `Handoff`/`HITLRequest`는 `BaseModel` + `Field`, 수신 단계는 `model_validate()`로 런타임 스키마 검증(`handoff.py:21-49`, `bridge_server.py:95-100`). 버전 혼재 없음.

### 4.5 OOP 정리
[사실] `src/` 내 `print(` 잔여 **0건**(grep 실측). 3차에서 `print`→`logger` 4건 전환 주장과 정합(모듈 전용 로거 `logging.getLogger(__name__)` 19곳 사용). `manifest.json` 익스텐션 상대 경로 정정(`manifest.json:8-9`). `runner.run()` CDP 결선 완료(`runner/__init__.py:79-89`).

---

## 5. 사용자 지적 반영

[사실] 다음 두 지적은 `docs/progress/03_cdp_bridge_implementation.md`(2026-08-13)에 **직접 인용**으로 기록되어 있으며, 2차 구현이 이를 사실 기반으로 반영했다.

### 5.1 지적 1: "CDP 한계 정의 말 것" → 실제 CDP 브릿지 구현
[사실] 사용자 직접 인용(Progress doc §8):
> "CDP 방식 사용해야 하는 것 아닌가? 한계라고 정의해 버리면 어떻게 하라는 거지?"

- **반영 결과:** CDP를 '한계/미구현'으로 치부하지 않고, 본 구현의 핵심 방식으로 채택. `cdp_bridge.py`의 `connect_over_cdp("http://127.0.0.1:9222")`로 실행 중 탭에 attach하여 **동일 탭 제어**를 제공(`cdp_bridge.py:50-66`).
- [사실] 설계 근거: AgentBrowser 본질은 인간이 이미 켜둔 헤드풀 크롬 세션을 에이전트가 이어받는 것. 새 브라우저 spawn(`launch_headed_chrome`)은 공유 세션이 아니므로 `connect_over_cdp` attach로 교체(Progress doc §10).

### 5.2 지적 2: "프로파일 공유 금지" → `profiles/` 별도 분리
[사실] 사용자 직접 인용(Progress doc §9):
> "기존 크롬 프로파일 공유는 안 됨. 패키지 내부 별도 프로파일 생성, 로그인은 사용자 직접 수행·저장되도록."

- **반영 결과:** `launcher.py`가 항상 패키지 내부 `profiles/<name>`을 `--user-data-dir`로 사용(`launcher.py:62`). 기본 시스템 크롬 프로파일은 절대 공유하지 않음.
- [사실] 부수 조치: 로그인·세션 데이터는 사용자가 직접 수행·저장(코드가 강제하지 않음), `.gitignore`에 `profiles/` 추가로 커밋 누수 차단(`.gitignore:34`).
- [사실] 위반 리스크 회피: 기본 프로파일 공유 시 (1)사용자 개인 인증·쿠키 직접 노출 (2)file lock 충돌/코루션 → 별도 `profiles/` 강제 분리(Progress doc §11).

### 5.3 지적 반영 요약
| 사용자 지적 | 반영 산출물 | 검증 |
|---|---|---|
| CDP를 한계로 정의 말 것 | `cdp_bridge.py` `connect_over_cdp` 실제 구현 | `cdp_bridge.py:60` 라인 인용 |
| 기존 프로파일 공유 금지 | `launcher.py` `profiles/<name>` + `.gitignore` | `launcher.py:62`, `.gitignore:34` |

---

## 6. 한계 및 후속

### 6.1 [반대증거] LLM stub (실제 호출 미수행)
[반대증거] `Runner`는 `LLMClient()`(env 기반 stub)의 `complete()`로 액션 계획 텍스트만 받는다(`runner/__init__.py:43,74`). 실제 LLM API 호출·프롬프트 엔지니어링·응답 파싱은 미구현. → **후속: 실제 LLM 연동 + 액션 파서.**

### 6.2 [반대증거] E2E 런타임 미수행
[반대증거] 진행 문서(Progress doc §17) 스스로 명시: "실제 Chrome 기동→익스텐션→bridge→CDP E2E 런타임 테스트 수행. LLM 실제 호출은 미수행(import/구문 검증만)." 현재 통과한 13건 테스트는 unit/integration 계층(stub·mock 기반)이며, **실제 헤드풀 Chrome 기동 → 익스텐션 로드 → bridge 수신 → CDP 제어** end-to-end 런타임은 검증되지 않았다. → **후속: 실제 런타임 E2E 스모크 테스트 추가.**

### 6.3 [반대증거] `profiles/` 정리 스크립트 필요
[반대증거] Chrome `user-data-dir` 특성상 `profiles/<name>`은 수백 MB 디스크를 점유하며 로그인 세션·캐시가 누적된다(`02_implementation_design.md` §9, §10). `.gitignore`는 커밋 누수만 막고 워크스페이스 로컬 디스크 점유는 별도 관리 대상. → **후속: `profiles/` 초기화·삭제 유틸 + 권한 700 설정**(§10 권고 미적용).

### 6.4 [반대증거] runner CDP 결선은 완료되나 실제 연결은 런타임 필요
[사실] `runner/__init__.py:79-89`에서 `CDPBridge` import → `connect()` → `control()`이 부가 결선되었으며, 실패 시 안전 fallback(LLM 결과만 반환)으로 동작한다.
[반대증거] 그러나 `connect()`는 `sync_playwright().chromium.connect_over_cdp(...)`를 호출하므로, **실제 실행 시 (a)playwright 설치 + (b)포트 9222로 기동 중인 헤드풀 Chrome 존재**가 전제된다. 현재까지 런타임에서 이 연결이 성공한 적은 없다(§6.2). → **후속: 런타임 CDP 연결 성공 확인 + 예외 시나리오 문서화.**

### 6.5 [반대증거] MV3 Service Worker 수명 제약
[반대증거] `background.js` 인메모리 `handoffs[]`/`hitlQueue[]`는 MV3 SW 수명 제약으로 장시간 유지 불가(`background.js:6-7` 자체 명시). 영속화는 후속 과제이며 실제 세션 상태는 Python bridge가 보유(§9). → **후속: 상태 영속 저장(lazy restore) 설계.**

### 6.6 [반대증거] HITL 실제 중단/재개 미구현
[반대증거] `orchestrator.receive_hitl()`은 로그(file/log console)만 기록하고 실제 실행 중단·인간 조치·`resume` 신호 복귀 흐름은 미구현(`orchestrator/__init__.py:90-115`). R2 캡차 위임의 종단부가 누락. → **후속: HITL pause/resume 상태머신.**

### 6.7 [반대증거] R5 분할 화면 협업 UI 미구현
[반대증거] `IDEA.md` §2 후속 범위로 명시된 분할 화면 협업 UI(R5)는 v1에서 미구현. 핸드오프 contract만 우선 확정. → **후속: 공유 세션 분할 뷰 UI.**

### 6.8 [권고] mypy strict 풀패스 별도 확인
[권고] `pyproject.toml`에 `strict=true`가 설정되어 있으나, 본 보고서 작성 시점에 mypy `strict` 전체 패스 여부는 ruff/pytest와 별도로 확인 필요. 3차 게이트에 포함 권장.

---

## 7. 결론

[사실] AgentBrowser는 3차에 걸쳐 (1)인간-에이전트 공유 브라우징 MVP 골격, (2)사용자 지적을 반영한 CDP 브릿지 실제 구현, (3)ruff 0 errors + pytest 13 passed + pydantic v2 일원화의 품질 게이트를 모두 디스크·실행 결과로 확보했다.

- **구현 완성도(사실):** R1(헤드풀 실제 Chrome 런처), R3(핸드오프 스키마+전송 경로 CS→BG→bridge:10899→Orchestrator→Runner), CDP 동일 탭 제어(`connect_over_cdp`), 별도 프로파일 분리(`profiles/`)가 소스 라인으로 검증 완료.
- **품질(사실):** `ruff 0.16.2` → 0 errors, `pytest` → 13 passed(100%), pydantic 2.13.4 v2 일원화, `print` 0건(logger 전환).
- **사용자 지적 반영(사실):** "CDP 한계 정의 말 것"→실제 CDP 브릿지, "프로파일 공유 금지"→`profiles/` 분리, 모두 직접 인용 기반 반영.
- **한계(반대증거):** LLM stub, E2E 런타임 미수행, `profiles/` 정리 스크립트 부재, 실제 CDP 연결은 런타임 전제, MV3 수명 제약, HITL 종단부·R5 UI 미구현. 이는 모두 명시적 후속 과제로 분리됨.

[권고] 다음 마일스톤은 **실제 런타임 E2E 스모크 테스트**(헤드풀 Chrome 기동→익스텐션→bridge→CDP) 수행과 **LLM 실제 연동**으로, 현재까지 코드 레벨로만 검증된 경로를 런타임에서 입증하는 것이 우선이다. 그 전까지는 "구현 완료"를 "코드·단위 검증 완료"로 한정하여 명시할 것을 권장한다.

---

### 부록: 증거 출처 일람
- `IDEA.md` §1·§2·§3(R1~R5)·§4·§6 (목적/범위/요구사항/구현경로/리스크)
- `docs/reports/02_implementation_design.md` §2·§8·§9·§10 (아키텍처/테스트매핑/리스크/CDP 브릿지)
- `docs/progress/03_cdp_bridge_implementation.md` (사용자 지적 직접 인용 + 디스크 파일 존재 확인)
- `docs/progress/04_dev_principles_tdd.md` (TDD 원칙)
- 실행 증거(2026-08-13): `ruff 0.16.2 → All checks passed!`, `pytest → 13 passed in 1.07s`, `pydantic 2.13.4`, `grep print( src/ → 0건`
- 소스 라인 인용: `launcher.py:62-76`, `bridge_server.py:32-35,82-102`, `cdp_bridge.py:50-66`, `background.js:6-7,15-35,87-88`, `orchestrator/__init__.py:60-67,69-115`, `runner/__init__.py:29-31,43,45-91`, `handoff.py:21-49,51`, `manifest.json:8-9`, `pyproject.toml:12-47`, `.gitignore:34`
- 디스크 실측: `find ./ -type f` 전체 파일 목록 대조
