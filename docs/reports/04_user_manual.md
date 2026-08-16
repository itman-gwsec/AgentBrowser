# 사용 메뉴얼 (AgentBrowser)

> 본 문서는 AgentBrowser를 실제로 사용(사전 준비 → 세션 기동 → 로그인 → 브릿지 기동
> → 핸드오프 → 문제 해결 → 주의사항)하는 절차를 단계별로 안내한다.
> 모든 명령과 동작은 저장소 실측 소스(`src/core/launcher.py`, `src/core/bridge_server.py`,
> `src/extension/*`, `.gitignore`, `README.md`)에 근거한다.
>
> 버전/이력: v1 (최초 작성). 대상 = `AgentBrowser` macOS 단일 머신 사용 시나리오.

---

## 0. 개요 — AgentBrowser가 무엇인가

AgentBrowser는 **사용자(인간)와 AI 에이전트가 동일한 실제(헤드풀) 크롬 세션을
공유**하는 협업형 브라우징 도구다. 인간이 시작한 웹 작업을 에이전트가 이어받아
수행하고, 캡차 등 인간 개입 지점에서는 다시 인간에게 넘긴다(HITL).

핵심 동작 흐름은 다음 5개 계층으로 구성된다(출처: `README.md` 아키텍처 섹션).

```
[Layer 0] launcher.py  → 헤드풀 Chrome 기동 (별도 프로파일 + CDP 포트 9222)
[Layer 1] Extension(MV3) → content_script가 DOM 추출 → background가 HTTP 전송
[Layer 2] bridge_server.py → 127.0.0.1:10899 에서 POST 수신
[Layer 3] Orchestrator / Runner(LLM stub) → 핸드오프 위임·액션 계획
[Layer 4] cdp_bridge.py → connect_over_cdp(9222) 로 동일 탭 제어
```

이 메뉴얼은 위 흐름을 **사용자가 직접 순서대로 기동**하는 방법을 다룬다.

---

## 사전 준비

본 단계는 최초 1회만 수행한다(이후 재기동 시에는 1단계부터 시작).

### 요구 환경 (사실, `README.md` §설치)

- **운영체제**: macOS. (`launcher.py:24`에 `/Applications/Google Chrome.app` 경로가
  하드코딩되어 있어 다른 OS에서는 기동되지 않는다.)
- **Python**: 3.11 이상. (`pyproject.toml`의 `target-version = "py311"`)
- **패키지 관리**: `uv` 권장(또는 `pip` + 표준 `venv`).
- **실제 Chrome**: 시스템에 Google Chrome이 설치되어 있어야 한다.

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

> 가상환경은 프로젝트 루트의 `.venv/` 에 생성된다. `.venv/` 는 `.gitignore` 대상이다.

### 2) 의존성 설치

```bash
# (A) requirements.txt 가 존재하는 경우 — 그대로 설치
.venv/bin/pip install -r requirements.txt
```

> ⚠️ **현재 상태(반대증거 동시보고)**: 본 저장소에는 `requirements.txt`와
> `pyproject.toml`의 `[project]` 의존성 섹션이 **아직 커밋되어 있지 않다**
> (`README.md` §설치 2) 참조). 따라서 (A)가 없는 경우 아래 (B) 실측 의존성을
> 직접 설치한다.

```bash
# (B) requirements.txt 부재 시 — 실측 검증된 최소 의존성
.venv/bin/pip install \
    playwright==1.62.0 \
    pydantic==2.13.4 \
    python-dotenv==1.2.2 \
    pytest==9.1.1 \
    ruff==0.16.2
```

> `pyproject.toml` 의존성으로 설치하려면 추후 `[project]` 섹션이 추가된 후
> `pip install -e .` 또는 `uv sync` 를 사용한다.

### 3) Playwright Chromium 브라우저 설치

```bash
.venv/bin/playwright install chromium
```

> `cdp_bridge.connect_over_cdp`와 launcher가 구동하는 실제 Chrome은 별개(시스템
> Chrome)이지만, CDP 제어 경로 검증 및 테스트에 Playwright chromium이 필요하다
> (`README.md` §설치 3).

### 4) 환경변수 설정 (선택)

```bash
cp config/env.example .env
# .env 편집: LLM_PROVIDER / LLM_MODEL / LLM_API_KEY
```

> 현재 `LLMClient`는 **stub** 이므로 값이 없어도 기동 가능하다. 실제 LLM 호출은
> 아직 연동되지 않았다(§주의사항 "현재 한계" 참조).

### 5) 사전 준비 완료 확인

```bash
# 가상환경 활성화 상태에서
.venv/bin/python --version      # 3.11 이상 확인
.venv/bin/python -c "import playwright, pydantic; print('ok')"
ls src/extension/manifest.json # 익스텐션 진입점 존재 확인
```

---

## 1단계: Chrome 프로파일 기동

별도 프로파일로 실제 Chrome을 기동한다. 이 프로파일은 기본 시스템 크롬과
**완전히 분리된 전용 세션**이다.

```bash
# 프로젝트 루트에서 (가상환경 활성화 상태)
.venv/bin/python -m core.launcher --profile default
```

- 터미널에 기동 로그와 함께 **pid** 가 출력된다.
  - 예: `Chrome 기동됨 (pid=12345, profile=default, port=9222)`
- `launcher.py`가 내부적으로 다음 플래그로 Chrome을 기동한다(`launcher.py:69-76`):
  - `--user-data-dir=profiles/default`  (전용 프로파일 디렉터리)
  - `--remote-debugging-port=9222`      (CDP 진입점)
  - `--load-extension=<절대경로>/src/extension`  (익스텐션 자동 로드)
  - `--no-first-run --no-default-browser-check`
- **`profiles/` 디렉터리가 자동 생성**된다(없으면 `launch_chrome()` 호출 시점에
  `os.makedirs` 로 생성, `launcher.py:64`).

### 확인 방법

```bash
# CDP 포트 응답 확인
curl -s http://127.0.0.1:9222/json/version
# → 웹소켓 디버깅 엔드포인트 정보가 JSON 으로 반환되면 정상
```

### 종료 방법

- 터미널에서 `Ctrl+C` 로 종료하거나, 출력된 pid 를 `kill <pid>` 한다.
- (권장) 단계를 거쳐 로그인 세션을 유지하려면 **기동한 채로 두고** 다음 단계로
  진행한다.

> 💡 다른 프로파일을 쓰고 싶으면 `--profile <이름>` 을 바꾸면 된다.
> 예: `--profile work` → `profiles/work` 가 생성된다.

---

## 2단계: 익스텐션 로드 확인

1단계에서 Chrome이 기동될 때 `src/extension` 가 **자동으로 로드**된다
(`--load-extension` 플래그, MV3). 로드 여부를 확인한다.

### 자동 로드 경로 (사실)

- 익스텐션 루트: `src/extension/`
- manifest 진입점: `config/manifest.json` 기준
  - background: `background/background.js`
  - content script: `content_script/content_script.js`

### 수동 확인

1. Chrome 주소창에 `chrome://extensions` 입력 후 이동.
2. 우측 상단 **개발자 모드(Developer mode)** 를 켠다.
3. "AgentBrowser" (또는 manifest 의 `name`) 항목이 목록에 있는지 확인.
4. 항목이 없다면: "압축해제된 확장 프로그램 로드(Load unpacked)" →
   `src/extension` 디렉터리 선택.

> ⚠️ 자동 로드가 안 된다면 launcher를 `--extension src/extension` (기본값) 그대로
> 쓰고 있는지, `src/extension/manifest.json` 이 존재하는지 확인한다(§문제 해결 (d)).

---

## 3단계: 로그인

**로그인은 사용자가 직접 수행**한다. AgentBrowser는 로그인/인증을 대행하지 않는다.

1. 1단계에서 기동된 Chrome 창에서 대상 사이트(예: 검색 포털, 커머스 등)로 이동.
2. 평소처럼 **직접 아이디/비밀번호로 로그인**.
3. 2단계 인증(MFA) 등도 사용자가 직접 처리.

### 세션 영속 (사실)

- 로그인 세션·쿠키·캐시는 `profiles/default` (`--user-data-dir`) 에 저장된다.
- 따라서 **다음 기동(1단계 재실행)에도 로그인이 유지**된다.
- `profiles/` 는 `.gitignore` 대상이므로 커밋되지 않는다(§주의사항).

> 💡 여러 사이트를 미리 로그인해 두면, 이후 핸드오프 작업 시 매번 로그인할
> 필요가 없다. 단, 세션 만료는 각 사이트 정책을 따른다.

---

## 4단계: Python 브릿지 기동

익스텐션이 보낸 핸드오프를 받을 **별도 터미널**에서 브릿지 서버를 기동한다.
(1단계 Chrome 터미널과는 다른 창을 쓴다.)

```bash
# 새 터미널 → 프로젝트 땅 → 가상환경 활성화
cd /Volumes/Data_Vault/ExoCortex/Projects/AgentBrowser
source .venv/bin/activate

.venv/bin/python -m core.bridge_server
```

- `bridge_server.py` 가 **`127.0.0.1:10899` 에서 수신 대기**한다
  (`bridge_server.py:32-35`, `HOST=127.0.0.1`, `PORT=10899`).
- 터미널에 `http://127.0.0.1:10899 수신 대기` 등의 로그가 뜨면 정상.
- 종료: `Ctrl+C`.

> 💡 브릿지는 **루프백(127.0.0.1)에만 bind** 되어 외부 네트워크 노출이 차단된다
> (`README.md` §핵심 설계 제약). 보안상 안전하다.

---

## 5단계: 핸드오프 트리거

이제 에이전트에게 작업을 넘길 수 있다. 핸드오프는 **웹페이지에서 발생**하며,
다음 경로로 흐른다(출처: `README.md` §사용법, `03_final_report.md` 흐름도).

```
content_script (DOM 추출)
   → chrome.runtime.sendMessage
   → background.js (forwardToAgent)
   → fetch POST http://127.0.0.1:10899/handoff
   → bridge_server (pydantic 검증)
   → Orchestrator.receive_handoff()
        → Runner.run()  (LLM stub → 액션 계획)
        → CDPBridge.connect()  (connect_over_cdp 9222)
        → 동일 탭 제어 (page.goto + 지터)
```

### 트리거 종류 (사실, `README.md` §(3))

- **트리거 A — 외부 메시지**: 페이지에서 아래를 전송.
  ```javascript
  window.postMessage({
    type: "AGENTBROWSER_HANDOFF",
    intent: "이 페이지의 상품 가격을 정리해 줘",
    constraints: "결제/로그인 금지"
  }, "*");
  ```
- **트리거 B — URL 변경 감지**: SPA의 `pushState/replaceState`·`popstate`로
  URL이 바뀌면 자동 `sendHandoff()`.
- **트리거 C — 캡차 감지**: `detectCaptcha()` 가 캡차 패턴을 감지하면
  `sendHITL("captcha_detected")` 로 인간 위임.

### 실행 예시

1. 1단계 Chrome에서 대상 페이지(예: 검색 결과 페이지)를 연다.
2. 개발자 도구 Console(F12) 에서 트리거 A 예시를 붙여넣어 실행.
3. 4단계 브릿지 터미널에 수신 로그가 찍히는지 확인.
4. `Orchestrator` 가 `Runner.run()` → `CDPBridge` 로 동일 탭을 제어한다
   (현재 LLM은 stub 이므로 실제 액션 생성은 미연동 — §주의사항).

---

## 문제 해결

### (a) 포트 9222 점유 — launcher 포트 변경

**증상**: 1단계 기동 시 다른 프로세스가 9222를 쓰고 있어 CDP 연결이 되지 않거나,
이전 Chrome 세션이 남아있다.

**대응**:
```bash
# 다른 포트로 기동
.venv/bin/python -m core.launcher --profile default --port 9223
```
- `launcher.py` 의 `--port` 인자로 변경 가능(`launcher.py:91-96`, 기본값 9222).
- 포트를 바꾸면 **브릿지/에이전트의 CDP 연결 대상도 동일 포트로 맞춰야 한다**
  (현재 `cdp_bridge.py` 는 `connect_over_cdp("http://127.0.0.1:9222")` 하드코딩 —
  포트 변경 시 소스 수정 필요, 추후 환경변수화 예정).
- 잔여 Chrome 프로세스 정리:
  ```bash
  pkill -f "remote-debugging-port=9222"   # 점유 프로세스 종료
  ```

### (b) bridge 연결 실패 — 방화벽 / 127.0.0.1 확인

**증상**: 익스텐션이 POST 를 보내도 4단계 브릿지에 도착하지 않음, 또는
`CDPBridge` 연결 시도에서 실패.

**대응**:
1. 브릿지가 **127.0.0.1(루프백)** 에서 리슨 중인지 확인:
   ```bash
   curl -s -X POST http://127.0.0.1:10899/handoff \
     -H "Content-Type: application/json" \
     -d '{"url":"https://example.com","dom_snapshot":"{}","intent":"test","timestamp":"2026-08-13T00:00:00"}'
   ```
   - 응답이 오면 브릿지 정상. 안 오면 4단계 기동 여부/포트 재확인.
2. 방화벽/보안 소프트웨어가 로컬 루프백 트래픽을 막지 않는지 확인(일반적으로
   macOS는 루프백을 차단하지 않음).
3. 익스텐션이 `127.0.0.1`(≠ `localhost` 도메인 리졸브 이슈 가능)으로 전송하는지
   `background.js` 의 `fetch` URL 확인.

### (c) 로그인 유실 — profiles/ 삭제 후 재로그인

**증상**: 기동했는데 이전 로그인이 사라짐, 또는 세션이 꼬임.

**대응**:
```bash
# 1단계 Chrome 먼저 종료 (Ctrl+C 또는 kill <pid>)
# profiles/default 삭제 (로그인/세션 데이터 초기화)
rm -rf profiles/default
# 다시 1단계 기동 → 3단계에서 직접 재로그인
.venv/bin/python -m core.launcher --profile default
```
- `profiles/` 는 **로컬 전용**이므로 삭제해도 저장소/원격에 영향 없음
  (`.gitignore` 대상).
- 자주 유실된다면: 기동 중 Chrome을 강제 종료(X 버튼이 아닌 `kill -9`)하지
  않도록 하고, 정상 종료 후 재기동한다.

### (d) 익스텐션이 chrome://extensions 에 안 보임

- `src/extension/manifest.json` 이 존재하는지 확인.
- launcher 가 `--extension src/extension` (기본값) 로 실행되는지 확인.
- Chrome 재시작 후 `chrome://extensions` 에서 "업데이트" 또는 Developr mode
  재토글. manifest 오류가 있으면 해당 페이지에 에러가 표시된다.

### (e) launcher 실행 시 "Chrome 바이너리를 찾을 수 없습니다"

- macOS 에 Google Chrome 이 설치되어 있는지 확인.
- `launcher.py:24` 경로 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
  가 실제 설치 경로와 다른 경우(비표준 설치)는 현재 하드코딩상 기동 불가 —
  표준 경로로 설치하거나 소스의 `CHROME_PATH` 를 수정해야 한다(다른 파일 수정
  금지 원칙상, 이 메뉴얼 범위 밖 작업임을 명시).

---

## 주의사항

### 1) 기본(시스템) 크롬 프로파일과 혼용 금지

- `launcher.py` 는 **항상 전용 `profiles/<name>`** 을 `--user-data-dir` 로 쓴다
  (`launcher.py:4-12`). 기본 시스템 크롬 프로파일을 공유하지 않는다.
- 평소 쓰는 개인 Chrome과 AgentBrowser 세션을 섞지 마라. 쿠키/로그인 혼재로
  인한 보안·추적 이슈를 방지하기 위함(설계 근거 R2, `launcher.py` docstring).
- 즉, AgentBrowser 용 작업은 **launcher로 기동된 창에서만** 수행한다.

### 2) `profiles/` 는 `.gitignore` 대상 — 절대 커밋 금지

- `.gitignore` 33~34행: `profiles/` 가 명시적으로 제외된다.
- 이 안에는 **로그인 세션·쿠키·개인 브라우징 데이터**가 들어있다.
- 실수로 `git add .` 하더라도 `profiles/` 는 추적되지 않지만, 강제
  `git add -f profiles/` 는 하지 말 것. 커밋에 포함되면 자격 증명이 유출된다.

### 3) 디스크 점유 — 정기 정리 필요

- Chrome `user-data-dir` 특성상 `profiles/<name>` 은 **수백 MB** 를 점유하며
  로그인 세션·캐시가 누적된다(`02_implementation_design.md` §9, §10).
- `.gitignore` 는 커밋 누수만 막고 **로컬 디스크 점유는 별도 관리 대상**이다.
- 디스크가 부족해지면 사용하지 않는 프로파일을 정리:
  ```bash
  du -sh profiles/*          # 점유 확인
  rm -rf profiles/<안쓰는이름>  # 삭제 (재로그인 필요)
  ```
- 현재 저장소에는 `profiles/` 초기화·삭제 유틸이 아직 없다(후속 과제).

### 4) macOS 전용

- `launcher.py` 가 macOS Chrome 경로를 하드코딩하므로 **Linux/Windows에서는
  기동되지 않는다**. 다른 OS 지원은 비목표(1차).

### 5) 현재 한계 (반대증거 동시보고 — 정직한 상태)

- **LLM은 stub**: `Runner` 가 호출하는 `LLMClient.complete()` 는 실제 LLM 호출
  없이 stub 이다(`README.md` §사용법 (4), `03_final_report.md`). 즉 핸드오프가
  수신되어도 **실제 액션 생성/자동 수행은 아직 동작하지 않는다**. 파이프라인
  경로(수신→Orchestrator→CDP 제어 호출)는 연결되어 있으나 LLM 지능부가 미연동.
- **런타임 CDP 연결 미확인**: `cdp_bridge.connect()` 는
  `connect_over_cdp("http://127.0.0.1:9222")` 를 호출하지만, **지금까지 런타임에서
  이 연결이 성공한 적은 없다**(`03_final_report.md` §6.2). 즉 1~4단계까지는
  검증 가능하나, 5단계의 실제 탭 제어는 아직 런타임 검증 전이다.
- **`[project]` 의존성 미커밋**: `requirements.txt` / `pyproject.toml` 의존성
  섹션이 아직 없어 사전 준비 2)를 그대로 따라 할 수 없을 수 있다(위 §사전 준비
  대안 (B) 참조).
- 위 항목들은 사용 흐름(이 메뉴얼)과는 별개의 **구현 완성도 이슈**이며, 추후
  개발 항목으로 분리되어 있다.

### 6) 보안/회피 금지

- 익스텐션·에이전트 계층에 `navigator.webdriver` 조작·봇 우회 로직은 **일절
  없다**(`README.md` §핵심 설계 제약). 인간유사 동작은 Python agent 레이어의
  "지터(무작위 대기)"뿐이다. 불법/부정 사용 목적으로 이 도구를改造하지 않는다.

---

## 부록: 빠른 전체 절차 요약

```bash
# [사전 준비] (최초 1회)
cd /Volumes/Data_Vault/ExoCortex/Projects/AgentBrowser
uv venv && source .venv/bin/activate
.venv/bin/pip install -r requirements.txt   # 부재 시 실측 의존성 설치
.venv/bin/playwright install chromium

# [터미널 1] Chrome 기동 (pid 출력, profiles/ 자동 생성)
.venv/bin/python -m core.launcher --profile default

# [2단계] Chrome에서 chrome://extensions 로 익스텐션 로드 확인

# [3단계] 대상 사이트에서 사용자가 직접 로그인 (세션은 profiles/default 에 영속)

# [터미널 2] 브릿지 기동 (:10899 리슨)
.venv/bin/python -m core.bridge_server

# [5단계] 페이지 Console 에서 핸드오프 트리거
# window.postMessage({type:"AGENTBROWSER_HANDOFF", intent:"...", constraints:"..."}, "*")
```

---

## 참고 소스 (인용)

- `src/core/launcher.py` — `--profile/--port` 인자, Chrome 기동 플래그, pid 출력.
- `src/core/bridge_server.py` — `HOST=127.0.0.1`, `PORT=10899` 고정, POST /handoff·/hitl.
- `src/extension/background/background.js` — `fetch POST 127.0.0.1:10899/handoff`.
- `src/core/cdp_bridge.py` — `connect_over_cdp("http://127.0.0.1:9222")`, 동일 탭 제어.
- `.gitignore` — `profiles/` 커밋 제외(L33-34).
- `README.md` — 설치/사용법/아키텍처(실측 근거).
- `docs/reports/03_final_report.md` — 전체 흐름도 및 현재 한계(LLM stub, CDP 미검증).
- `docs/reports/02_implementation_design.md` — 별도 프로파일 원칙, 디스크 점유 경고.
