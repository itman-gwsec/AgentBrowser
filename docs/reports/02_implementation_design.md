# AgentBrowser 구현 설계안 (요약 v1)

- **작성일:** 2026-08-12
- **버전:** v1
- **상태:** 확정 리포트 (최종)
- **작성 근거:** 작업 지시서, `IDEA.md` 직접 인용, Chrome MV3 표준, HITL 패턴 문헌
- **표기 규칙:** `[사실]` = `IDEA.md`/작업지시로 검증된 항목. `[권고]` = evidence 기반 권장, 필수 아님. `[반대증거]` = 상충하는 사실/경고.

## 1. MVP 범위
[사실] `IDEA.md` §2는 MVP 경계를 "헤드풀(headed) 실제 크롬 브라우징, DOM 추출·저장, 인간→에이전트 위임 시나리오 1종"으로 명시하고, 후속 범위로 "실시간 분할 화면 협업 UI(R5), 보안/샌드박싱, 법적 검토"를 둔다. [권고] v1은 협업 UI·보안·법적 리스크를 후속으로 미루고 위임 1종에 집중하되, R3 핸드오프 스키마만 먼저 확정하여 후속 확장의 contract로 삼는다. 비목표(§2)인 별도 백엔드 서버·크롬 외 브라우저는 v1에서 제외한다. §5 기술 로드맵의 '상' 난이도 항목(상태전이 프로토콜·보안)도 v1에서는 핸드오프 스키마 설계에만 부분 반영한다.

## 2. 아키텍처 (메시징 경계)
[사실] `IDEA.md` §4는 구현 경로를 "크롬 익스텐션(Content Script + Background)"으로 규정하며, §4 책임 분리는 익스텐션을 "공유 세션·핸드오프·협업 UI" 전용으로 한정한다. [권고] CS가 페이지 DOM·상호작용을 캡처하면 Background(Service Worker)가 메시지를 라우팅하고, Python 계층(core/agent)이 도메인 로직·LLM·오케스트레이션을 수행하는 3경계를 둔다. CS↔Background는 `chrome.runtime` 메시징, Background↔Python은 로컬 IPC/WebSocket bridge로 격리한다. Python bridge는 세션 상태를 메모리에 보유하여 §9의 MV3 수명 제약 보완점이 된다.

## 3. 핸드오프 스키마 (R3)
[사실] `IDEA.md` §3 R3은 위임 시 "URL, DOM 스냅샷, 작업 의도, 제약"을 함께 전달한다고 명시한다. [권고] 아래 JSON 스키마 초안을 핸드오프 contract로 채택한다.

```json
{
  "url": "string",
  "dom_snapshot": "object",
  "intent": "string",
  "constraints": ["string"],
  "timestamp": "string (ISO8601)"
}
```

## 4. 봇 회피
[사실] `IDEA.md` §3 R2는 "헤드풀 환경과 인간 유사 동작(자연스러운 타이밍·궤적)"으로 봇 탐지를 완화하며, §4는 익스텐션 자체가 `navigator.webdriver` 등으로 탐지될 수 있어 "회피용으로는 부적합"이라 본다. [권고] 회피는 헤드풀 브라우저 자체 동작(타이밍 지터·자연스러운 마우스 궤적·fingerprint 일관성)에 위임하고, 익스텐션 레이어는 회피 목적으로 사용하지 않는다.

## 5. DOM 추출·저장
[사실] `IDEA.md` §3 R4는 "페이지 DOM에서 필요한 콘텐츠를 추출해 구조화하여 저장"한다. [권고] CS 단계에서 CSS 선택자/구조 기반으로 노드를 추출하고, R3 `dom_snapshot`과 동일한 JSON 포맷으로 영속 저장하여 위임·재사용한다.

## 6. HITL (캡차 위임)
[사실] `IDEA.md` §3 R2는 "캡차 등 인간 확인이 필요한 지점은 즉시 인간에게 위임(HITL)" 처리한다. [권고] 에이전트가 캡차 감지 시 실행을 중단하고 인간에게 화면·컨텍스트를 넘기며, 인간 조치 후 `resume` 신호로 에이전트가 이어받는 흐름을 표준화한다(HITL 패턴; live 미검증 — canonical URL만 인용, 검색 백엔드 도달 불가).

## 7. 기술 스택
[사실] Python/익스텐션 분리는 `IDEA.md` §4 구현 경로로 사실적 근거를 가진다. [권고] Python은 `uv`(패키지·가상환경) + `pydantic`(핸드오프 스키마 검증)로 운용한다. 익스텐션은 빌드 단계가 없는 **MV3 vanilla JS**를 권고한다 — TypeScript는 타입 안정성은 높으나 번들·컴파일 설정이 추가되어 v1 MVP 공수를 키우기 때문이다. pydantic은 R3 스키마의 런타임 검증과 문서화를 동시에 제공하여 핸드오프 신뢰성을 높인다.

## 8. 테스트 매핑
[권고] `tests/unit`은 스키마 검증·추출 로직·오케스트레이션 모듈을, `tests/integration`은 CS↔Background 메시징·Background↔Python bridge 동작을 검증하도록 매핑한다(폴더 구조 제안서 §3 `tests/` 관행 준용). CI에서 두 계층을 분리 실행하여 회귀를 조기에 차단한다.

## 9. 리스크 대응
[사실] `IDEA.md` §6은 "MV3의 백그라운드 수명·API 제한이 장시간 세션 유지 설계에 영향"과 "헤드풀 성능(실제 UI 렌더링 부하)"을 명시한다. [권고] MV3 대응은 이벤트 기반 Service Worker 설계(상태 영속 저장·lazy restore)로 두고, 헤드풀 성능은 동시 세션 수 제한으로 완화한다. [반대증거] 장시간 유지 세션에 MV3 Service Worker를 쓰는 것은 수명 제약으로 난이도가 높아, Python bridge가 세션 상태를 보유하는 보완 설계가 필요하다. 법적 리스크(§6)는 v1 블로커가 아니므로 차후 과제로 분리한다. [반대증거] 별도 프로파일(`profiles/<name>`)은 Chrome `user-data-dir` 특성상 수백 MB의 디스크를 점유하며 로그인 세션·캐시가 누적된다. 정기 정리 스크립트(`profiles/` 초기화·삭제 유틸)가 필요하고, `.gitignore`로 커밋 누수를 막더라도 워크스페이스 로컬 디스크 점유는 별도 관리 대상이다.

## 10. CDP 브릿지 아키텍처

[사실] 별도 프로파일 원칙: 기본 시스템 크롬 프로파일은 공유하지 않는다. `launcher.py`는 항상 패키지 내부 `profiles/<name>` 디렉터리를 `--user-data-dir`로 사용하며(`launcher.py:58`), 이 경로는 `.gitignore`의 `profiles/` 대상으로 커밋에서 제외된다(검증됨). 로그인·세션 데이터는 사용자가 직접 수행·저장하고 `user-data-dir`에 영속된다.

[사실] 런처 기동 플래그: `launch_chrome()`은 `--user-data-dir=profiles/<name>` + `--remote-debugging-port=9222` + `--load-extension=src/extension`으로 실제(macOS) Chrome을 헤드풀 기동한다(`launcher.py:65-72`). 포트 9222가 CDP 진입점이다.

[사실] 통신 경로: 익스텐션 `background.js`의 `forwardToAgent()`가 핸드오프를 `fetch("http://127.0.0.1:10899/handoff", POST)`로 전송하고(`background.js:17`), `bridge_server.py`가 수신 후 `Orchestrator.receive_handoff()`로 위임한다(`bridge_server.py:87-92`). 이어 `runner.run()`이 LLM으로 액션 계획을 생성한다(`runner/__init__.py:42`). `cdp_bridge.py`의 `CDPBridge.connect()`는 `connect_over_cdp("http://127.0.0.1:9222")`로 실행 중 탭에 attach하여 동일 탭을 제어한다(`cdp_bridge.py:60-74`; 기존 context/page 재사용).

[사실] 보안: `bridge_server.py`는 bind host를 `127.0.0.1`로 고정해 외부 노출을 차단한다(`bridge_server.py:29`). `profiles/`는 `.gitignore` 대상이다.

[권고] 프로파일 디렉터리 권한을 `700`으로 설정해 타 사용자 접근을 제한한다. [반대증거] `CDPBridge.control()`은 현재 지터·이동 스텁이며, runner 자동 결선은 아직 구현되지 않았다(현재 `runner.run()`은 CDPBridge를 호출하지 않음) — 후속 결선 과제.

## 11. evidence / 외부 출처
- Chrome MV3: `https://developer.chrome.com/docs/extensions/mv3/` (live 미검증 — SearXNG 도달 불가, canonical URL만 인용)
- HITL 패턴: `https://docs.langchain.com/oss/python/langgraph/quickstart` (live 미검증)
- 인-리포지토리: `IDEA.md` §2·§3(R1–R5)·§4·§6 직접 인용.
