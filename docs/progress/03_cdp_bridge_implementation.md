# CDP 브릿지 구현 및 별도 프로파일 원칙 결정 (2026-08-13)

## 결정
1. 1차 MVP의 "브릿지 미구현/stub" 상태를 CDP 기반 실제 브릿지로 교체 구현한다.
2. 기본(사용자) 크롬 프로파일 공유를 금지하고, 패키지 내부 `profiles/<name>` 별도 생성 원칙을 확정한다.

## 근거 (사실)
- [사실] 사용자 지적(직접 인용): "CDP 방식 사용해야 하는 것 아닌가? 한계라고 정의해 버리면 어떻게 하라는 거지?" — CDP를 '한계/미구현'으로 치부할 것이 아니라 본 구현 방식으로 채택할 것을 요구.
- [사실] 사용자 지적(직접 인용): "기존 크롬 프로파일 공유는 안 됨. 패키지 내부 별도 프로파일 생성, 로그인은 사용자 직접 수행·저장되도록." — 공유 금지·분리 원칙 직접 지시.
- [사실] AgentBrowser 본질은 인간이 이미 켜둔 헤드풀 크롬 세션을 에이전트가 이어받는 것. 새 브라우저 spawn(`launch_headed_chrome`)은 공유 세션이 아님 → `connect_over_cdp` attach로 교체.
- [사실] 기본 프로파일 공유 시 (1)사용자 개인 인증·쿠키 직접 노출 (2)file lock 충돌/코루션 리스크 → 별도 `profiles/` 강제 분리.
- [사실] 구현 완료 파일(디스크 확인): `launcher.py`(`--user-data-dir=profiles/<name> --remote-debugging-port=9222 --load-extension=src/extension`), `bridge_server.py`(HTTP POST :10899, 127.0.0.1 바인드), `cdp_bridge.py`(`connect_over_cdp` attach+동일 탭 제어), `background.js`(fetch POST :10899 실제 전송), `src/core/orchestrator/__init__.py`(CDPBridge 연동 L83-91 안전 fallback), `.gitignore`(`profiles/` 추가 L34), `02_implementation_design.md`(§10 CDP 브릿지 아키텍처 보강).
- [반대증거] `profiles/`는 수백MB 점유·로그인 누적 → 정리 스크립트 필요(§9 기록). `runner.run()` 내부 CDP 자동 호출은 미결선(현재 orchestrator 경로로 동작) → 후속 과제.
- [권고] `profiles/` 디렉터리 권한 700 설정으로 타 사용자 접근 제한(§10).

## 적용
- 2차 구현 완료. 실제 Chrome 기동→익스텐션→bridge→CDP E2E 런타임 테스트 수행. LLM 실제 호출은 미수행(import/구문 검증만).

## 버전/이력
- 2026-08-13: v1. IDEA.md R1/R2/R3 및 사용자 지적(CDP 필수·프로파일 분리) 직접 인용 기반. 디스크 파일 존재·라인 인용 확인 완료.

## 참조
- docs/reports/02_implementation_design.md §10
- src/core/{launcher,bridge_server,cdp_bridge}.py
- src/core/orchestrator/__init__.py
- src/extension/background/background.js
- .gitignore
