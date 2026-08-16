# AgentBrowser

> 인간과 AI 에이전트가 **동일한 실제(헤드풀) 크롬 세션**을 공유하며, 인간이 시작한
> 웹 작업을 에이전트가 이어받아 수행하고 필요 시 다시 인간에게 넘기는
> 협업형 브라우징 환경.

본 문서는 AgentBrowser의 개요·아키텍처·설치·사용법·개발 원칙·한계를 다룬다.
모든 서술은 저장소 실측 소스(`IDEA.md`, `src/`, `config/manifest.json`,
`pyproject.toml`, 테스트 결과)에 근거한다.

---

## 목차

1. [개요](#개요)
2. [아키텍처](#아키텍처)
3. [설치](#설치)
4. [사용법](#사용법)
5. [개발](#개발)
6. [한계 및 후속 과제](#한계-및-후속-과제)

---

## 개요

### 목적
사용자와 AI 에이전트가 **같은 실제 크롬 브라우징 세션**을 공유한다. 인간이 직접
시작한 웹 작업(검색·조회·자동화)을 에이전트가 인계받아 수행하고, 필요 시 다시
인간에게 넘기는 협업형 브라우징 환경을 제공한다. 기존 자동화 도구는
인간-에이전트 핸드오프를 지원하지 않으므로, 이를 핵심 가치로 삼는다.
(출처: `IDEA.md` §1, §2)

### 핵심 요구사항 (IDEA.md §3, R1~R5)
| 요구 | 설명 | 난이도 |
|------|------|--------|
| **R1** 헤드풀 실제 크롬 | 화면이 있는(headed) 실제 크롬으로 동작. 헤드리스는 인간 유사 동작·시각적 협업과 모순되어 채택하지 않음. | 상 |
| **R2** 봇 탐지 회피 + 캡차 인간 위임 | 에이전트는 헤드풀 환경과 인간 유사 동작(자연스러운 타이밍·궤적)으로 봇 탐지를 완화. 단 캡차 등 인간 확인 지점은 즉시 인간에게 위임(HITL). | 상 |
| **R3** 인간→에이전트 위임/핸드오프 | 인간이 진행 중인 작업을 에이전트에게 넘김. 위임 시 URL·DOM 스냅샷·작업 의도·제약을 함께 전달. | 중 |
| **R4** DOM 추출·저장 | 페이지 DOM에서 필요한 콘텐츠를 추출해 구조화하여 저장. | 중 |
| **R5** 분할 화면 협업 | 사용자와 에이전트가 분할 화면으로 같은 세션을 함께 봄. | 상 |

> **난이도 표기 원칙**: 위 요구/구현 항목은 "불가능"이 아니라
> **난이도(상/중/하)와 필요 공수**로 분류한 것이다(`IDEA.md` §5 분류 기준).
> 상 = 공수 집중 항목, 하 = 비교적 단순 항목.

### 범위
- **대상 활동**: 웹 검색 + 일반 웹 자동화(양쪽 포함).
- **MVP 경계**: 헤드풀 실제 크롬 브라우징, DOM 추출·저장, 인간→에이전트 위임
  시나리오 1종 우선 구현.
- **후속 범위**: 실시간 분할 화면 협업 UI(R5), 보안/샌드박싱(R2 상), 법적 검토.
- **비목표(1차)**: 별도 백엔드 서버 운영, 크롬 외 브라우저 지원.

### 차별화 및 책임 분리
- Playwright/Puppeteer/MCP 등은 자동화에 강하지만 **공유 세션·인간-에이전트
  핸드오프·실시간 협업 UI**를 제공하지 않는다.
- 봇 탐지 회피의 책임은 **헤드풀 + 인간 유사 동작(브라우저 자체 동작)**에 있다.
  익스텐션 자체는 `navigator.webdriver` 등으로 탐지될 수 있어 회피용으로는
  **부적합**하므로, 익스텐션 레이어는 공유 세션·핸드오프·협업 UI에만 사용한다.
  (`IDEA.md` §4, `src/extension/*` 주석 일치)

---

## 아키텍처

### 계층 흐름도
```
┌─────────────────────────────────────────────────────────────────────┐
│ [Layer 0] 헤드풀 Chrome 기동 (src/core/launcher.py)                   │
│   • 실제 Chrome 바이너리 (/Applications/Google Chrome.app)           │
│   • --user-data-dir=profiles/<name>  (기본 프로파일 공유 금지)        │
│   • --remote-debugging-port=9222                                   │
│   • --load-extension=src/extension  (MV3 익스텐션 자동 로드)          │
└───────────────────────────────┬─────────────────────────────────────┘
                                 │ 공유 세션 (동일 탭/컨텍스트)
┌───────────────────────────────▼─────────────────────────────────────┐
│ [Layer 1] Chrome Extension (MV3)  config/manifest.json               │
│                                                                     │
│   content_script/content_script.js                                  │
│     • DOM 추출(R4): extractDOM()                                    │
│     • 캡차/HITL 감지: detectCaptcha()                               │
│     • 핸드오프 전송: sendHandoff() → chrome.runtime.sendMessage      │
│                                                                     │
│   background/background.js  (Service Worker)                        │
│     • 메시지 라우터 (HANDOFF / HITL / GET_HANDOFFS)                  │
│     • forwardToAgent() → fetch POST 127.0.0.1:10899/handoff         │
│     • sendHITL()       → fetch POST 127.0.0.1:10899/hitl            │
└───────────────────────────────┬─────────────────────────────────────┘
                                 │ HTTP POST (loopback, 루프백 고정)
┌───────────────────────────────▼─────────────────────────────────────┐
│ [Layer 2] Bridge HTTP Server (src/core/bridge_server.py)             │
│   • ThreadingHTTPServer, HOST=127.0.0.1, PORT=10899 (BRIDGE_PORT)   │
│   • POST /handoff → Handoff.model_validate → Orchestrator            │
│   • POST /hitl    → HITLRequest.model_validate → Orchestrator       │
└───────────────────────────────┬─────────────────────────────────────┘
                                 │ 위임
┌───────────────────────────────▼─────────────────────────────────────┐
│ [Layer 3] Python Core / Agent                                       │
│                                                                     │
│   src/core/orchestrator/__init__.py                                 │
│     • receive_handoff() → Runner.run() 위임 (§9 상태 보유자)         │
│     • receive_hitl()     → console/file(JSONL) 로그                  │
│                                                                     │
│   src/agent/runner/__init__.py  (Runner)                            │
│     • _build_prompt(Handoff) → 프롬프트 조립                        │
│     • 인간유사 지터 스텁 (time.sleep 0.2~1.2s)                      │
│     • self.llm.complete(prompt)  ← LLMClient STUB                   │
│                                                                     │
│   src/core/llm/__init__.py  (LLMClient, stub)                       │
│     • env 기반 (LLM_PROVIDER/MODEL/API_KEY) — 실제 호출 없음        │
│                                                                     │
│   src/agent/tools/__init__.py                                       │
│     • parse_dom(), summarize_handoff(), ToolRegistry                │
└───────────────────────────────┬─────────────────────────────────────┘
                                 │ 동일 탭 제어
┌───────────────────────────────▼─────────────────────────────────────┐
│ [Layer 4] CDP Bridge (src/core/cdp_bridge.py)                       │
│   • connect_over_cdp("http://127.0.0.1:9222")                       │
│   • 기존 context/page 재사용 (익스텐션 탭 보존)                      │
│   • control(Handoff): page.goto(url) + 지터                         │
└─────────────────────────────────────────────────────────────────────┘
```

### 데이터 컨트랙트 (pydantic v2, `src/core/handoff.py`)
```python
class Handoff(BaseModel):       # R3 인간→에이전트 위임
    url: str                    # 위임 대상 페이지 URL
    dom_snapshot: str           # JS가 전송하는 JSON 직렬화 DOM 스냅샷(str)
    intent: str = ""            # 작업 의도 (미지정 시 "")
    constraints: str = ""       # 위임 제약 (예: "로그인 금지")
    timestamp: datetime         # 핸드오프 생성 시각
    version: str = "1.0"        # 스키마 버전 (하위 호환)

class HITLRequest(BaseModel):   # R6 캡차 등 인간 개입 위임
    url: str
    reason: str                 # 예: "captcha_detected"
    timestamp: datetime
```

### 핵심 설계 제약
- **보안**: 브릿지 서버는 `127.0.0.1`(루프백)에만 bind하여 외부 노출 차단.
- **회피 금지**: 익스텐션/agent 계층에 `navigator.webdriver` 조작·봇 우회 로직
  일절 없음(R2 위반 금지). 허용되는 인간유사 동작은 Python agent 레이어의
  "지터(무작위 대기)"뿐.
- **MV3 수명 제약**: Service Worker는 장시간 유지 불가하므로 영속 상태는
  Python `Orchestrator`가 인메모리로 보유(§9).
- **순환 import 방지**: `bridge_server`는 Orchestrator를 최상단 import,
  `cdp_bridge`는 runner에서 지연(lazy) import.

---

## 설치

### 요구 환경
- macOS (실제 Chrome 바이너리 경로 하드코딩: `/Applications/Google Chrome.app`)
- Python 3.11 (`pyproject.toml` target-version `"py311"`)
- `uv` (권장) 또는 `pip` + 가상환경

### 1) 가상환경 생성
```bash
cd /Volumes/Data_Vault/ExoCortex/Projects/AgentBrowser

# uv 사용 (권장)
uv venv
source .venv/bin/activate

# 또는 표준 venv
python3 -m venv .venv
source .venv/bin/activate
```

### 2) 의존성 설치
> ⚠️ **현재 저장소에는 `requirements.txt`와 `pyproject.toml`의 `[project]`
> 의존성 섹션이 아직 커밋되어 있지 않다**(한계/후속 과제 참조). 따라서 아래는
> 실측 설치된 패키지를 바탕으로 한 최소 설치 명령이다.

```bash
# 실측 검증된 주요 의존성 (저장소 .venv 기준)
.venv/bin/pip install \
    playwright==1.62.0 \
    pydantic==2.13.4 \
    python-dotenv==1.2.2 \
    pytest==9.1.1 \
    ruff==0.16.2
```

### 3) Playwright Chromium 브라우저 설치
```bash
.venv/bin/playwright install chromium
```
> `cdp_bridge.connect_over_cdp`와 `launcher`가 구동하는 실제 Chrome은
> 별개(시스템 Chrome)이지만, CDP 제어 경로 검증 및 테스트에 Playwright
> chromium이 필요하다.

### 4) 환경변수(선택)
```bash
cp config/env.example .env
# .env 편집: LLM_PROVIDER / LLM_MODEL / LLM_API_KEY
# (현재 LLMClient는 stub — 값이 없어도 기동 가능)
```

---

## 사용법

### (1) launcher로 Chrome 기동
```bash
# 프로파일 이름 지정 (profiles/<name> 생성, 기본 프로파일과 분리)
.venv/bin/python -m core.launcher --profile default --port 9222

# 내부적으로 실행되는 Chrome 플래그:
#   --user-data-dir=profiles/default
#   --remote-debugging-port=9222
#   --load-extension=src/extension   ← 익스텐션 자동 로드
#   --no-first-run --no-default-browser-check
```
> 기본 시스템 크롬 프로파일을 공유하지 않도록 **항상 전용
> `profiles/<name>`을 user-data-dir로 사용**한다. 로그인/세션 데이터는
> `.gitignore`의 `profiles/`로 커밋에서 제외된다.

### (2) 익스텐션 로드
- **자동**: 위 launcher 실행 시 `--load-extension=src/extension`로 MV3 익스텐션이
  자동 로드된다(`config/manifest.json` 기준).
- **수동(확인용)**: Chrome 주소창에 `chrome://extensions` → 개발자 모드 →
  "압축해제된 확장 프로그램 로드" → `src/extension` 선택.

### (3) 핸드오프 트리거
익스텐션(Content Script)은 다음 경로로 핸드오프를 발생시킨다:
- **트리거 A — 외부 메시지**: 페이지에서
  `window.postMessage({type:"AGENTBROWSER_HANDOFF", intent, constraints}, "*")`
- **트리거 B — URL 변경 감지**: SPA `pushState/replaceState`·`popstate`로
  URL이 바뀌면 자동 `sendHandoff()`
- **트리거 C — 캡차 감지**: `detectCaptcha()`가 캡차 패턴을 감지하면
  `sendHITL("captcha_detected")`로 인간 위임

```javascript
// 예: 페이지 콘솔에서 직접 위임 요청
window.postMessage({
  type: "AGENTBROWSER_HANDOFF",
  intent: "이 페이지의 상품 가격을 정리해 줘",
  constraints: "결제/로그인 금지"
}, "*");
```

### (4) Python 수신 → CDP 제어
별도 터미널에서 브릿지 서버를 기동하면 익스텐션 POST를 수신한다:
```bash
.venv/bin/python -m core.bridge_server
# → http://127.0.0.1:10899 수신 대기 (Ctrl+C 종료)
```
수신 흐름:
1. `background.js`가 `POST /handoff`로 `Handoff` 전송.
2. `bridge_server`가 pydantic 검증 후 `Orchestrator().receive_handoff()`.
3. `Runner.run()` → 프롬프트 조립 → `LLMClient.complete()`(현재 **stub**) →
   `CDPBridge.connect()` + `control()`로 **동일 탭 제어**(URL 이동 + 지터).

> **프로파일 로그인은 사용자가 직접 수행**한다. AgentBrowser는 로그인/인증을
> 대행하지 않으며, 세션 데이터는 사용자 전용 `profiles/`에 보관된다.

---

## 개발

### 개발 원칙 (실측 준수)
- **TDD**: 테스트 우선. 현재 `tests/unit`(3) + `tests/integration`(2) 구성.
- **ruff 클린 100%**: `pyproject.toml` 기준 line-length=100, py311,
  select=\[E,F,I,B,UP,RUF,TRY,DTZ,C4,SIM,PL\], ignore=\[\](BLE001만 예외).
- **pydantic v2**: 모든 데이터 컨트랙트는 `BaseModel` 기반.
- **OOP**: 핵심 동작은 클래스(`Orchestrator`, `Runner`, `CDPBridge`,
  `LLMClient`, `ToolRegistry`)로 캡슐화.

### 검증 상태 (실측)
```bash
$ .venv/bin/python -m pytest tests/ -q
.............                                    [100%]
13 passed in 1.57s

$ .venv/bin/ruff check .
All checks passed!
```
> 위 수치는 작성 시점 저장소에서 실제 실행한 결과이다.

### 테스트 실행
```bash
# 전체 테스트
.venv/bin/python -m pytest tests/ -q

# 단위 / 통합 분리
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m pytest tests/integration -q

# 린트
.venv/bin/ruff check .
.venv/bin/ruff format --check .   # 포맷 검사(옵션)
```

### 디렉터리 구조
```
src/
  extension/
    content_script/content_script.js   # DOM 추출·캡차감지·핸드오프
    background/background.js            # MV3 SW, 메시지 라우터, Python 전송
  core/
    launcher.py        # 헤드풀 Chrome 기동 (프로파일/포트/익스텐션)
    bridge_server.py   # 127.0.0.1:10899 HTTP 수신
    cdp_bridge.py      # connect_over_cdp → 동일 탭 제어
    handoff.py         # pydantic v2 Handoff/HITLRequest
    orchestrator/      # receive_handoff / receive_hitl (상태 보유자)
    llm/               # LLMClient (stub)
    browser/           # 브라우저 관련 (확장 예정)
  agent/
    runner/            # Handoff → LLM → 액션 계획 (stub)
    tools/             # parse_dom / summarize_handoff / ToolRegistry
config/
  manifest.json        # MV3 매니페스트
  env.example          # LLM 환경변수 샘플
tests/
  unit/  integration/  # pytest (pythonpath=[src])
pyproject.toml         # ruff/pytest/mypy 설정 (strict)
```

---

## 한계 및 후속 과제

> 아래 항목은 **현재 미구현/미검증 상태**를 명시한 것이지 "불가능"이 아니다.
> 모두 IDEA.md의 난이도 분류(상/중/하)에 따라 후속 공수로 해결 가능한 과제다.

### 1) LLM 실제 호출이 stub 상태
- `src/core/llm/__init__.py`의 `LLMClient.complete()`는 프롬프트 앞 50자를
  잘라 `[STUB] ...` 문자열을 반환할 뿐 **실제 API 호출을 하지 않는다**.
- `src/agent/runner/__init__.py`의 제어 로직도 MVP 스텁(URL 이동 + 지터)이며,
  정교한 클릭·타이핑·궤적 제어는 후속 단계.
- **후속**: `complete()`를 실제 provider(openai/anthropic 등) 호출로 교체,
  `config/env.example`의 `LLM_API_KEY` 연동.

### 2) E2E 런타임 테스트 미수행
- 현재 13개 테스트는 **실제 Chrome을 기동하거나 CDP에 연결하지 않는다**.
  - `tests/integration/test_bridge_server.py`: 스레드 바인딩 HTTP 서버 +
    `Orchestrator.receive_handoff` 스파이로 위임 경로만 검증.
  - `tests/integration/test_launcher.py`, `tests/unit/*`: 모델/로직 단위 검증.
- 즉 `launcher → Chrome 기동 → 익스텐션 POST → CDP 동일 탭 제어` 전체
  **엔드투엔드 경로는 아직 런타임에서 검증되지 않았다**.
- **후속**: 헤드풀 Chrome 기동 + `connect_over_cdp`까지 포함하는 E2E
  통합 테스트(별도 CI/수동 시나리오) 추가.

### 3) `profiles/` 정리 스크립트 필요
- `launcher.py`는 매 기동 시 `profiles/<name>`을 생성하며, `.gitignore`로
  커밋에서 제외되나 **누적 프로파일을 정리하는 스크립트가 없다**.
- `scripts/`에는 현재 `setup.sh`·`build.sh` 스텁만 존재(실질 동작 없음).
- **후속**: `profiles/` 폴더 정리/초기화 스크립트(`scripts/clean_profiles.sh` 등)
  추가.

### 4) 의존성 선언 누락 (설치 관련 반대증거)
- `requirements.txt`가 없고 `pyproject.toml`에도 `[project]` 의존성 섹션이
  없어, 본 README 설치 절은 실측 패키지 기반으로 작성되었다.
- **후속**: `pyproject.toml`에 `[project.dependencies]` 또는
  `requirements.txt` 커밋하여 일관된 설치 보장.

### 5) 아직 미구현된 R 요구사항
- **R5 분할 화면 협업 UI**: 협업 UI 자체는 미구현(익스텐션 메시지 라우터만 존재).
- **R2 보안/샌드박싱(상)**: 에이전트 조작 격리·권한 경계 설계 미반영.
- **에러복구(중)**: 위임 실패 시 롤백/재시도 정책 미정의.
- **KPI(하)**: 작업 성공률·위임 전환 시간 등 측정 지표 미정의.

---

## 참고 소스 (evidence)
- `IDEA.md` — 목적·범위·핵심 요구(R1~R5)·난이도 분류·리스크
- `config/manifest.json` — MV3 매니페스트(권한·SW·content_script)
- `src/core/{launcher,bridge_server,cdp_bridge,handoff,orchestrator}/` — 코어 흐름
- `src/extension/{content_script,background}/*.js` — 익스텐션 동작
- `src/agent/{runner,tools}/` — 러너/도구 계층
- `pyproject.toml` — ruff(line-length 100, strict)·pytest·mypy(strict) 설정
- 실측: `pytest 13 passed`, `ruff check → All checks passed`
