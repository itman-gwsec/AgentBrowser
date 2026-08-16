# AgentBrowser 폴더 구조 제안서 (v2)

- **작성일:** 2026-08-12
- **버전:** v2 (기존 `01_folder_structure_proposal.md` 덮어쓰기)
- **상태:** 제안 (최종 리포트)
- **작성 근거:** 작업 지시서 요구사항 #3, 사용자 컨벤션, `IDEA.md`, Chrome MV3 표준 명세
- **표기 규칙:** `[사실]` = 작업 지시/사용자 컨벤션/인-리포지토리 문서로 검증된 항목. `[권고]` = evidence 기반 권장이나 필수는 아님.

## 1. 문서 컨벤션 (사용자 규칙 — 사실)

[사실] `docs/reports/` 는 확정된 **최종 리포트** 보관소이며, 본 문서는 그곳에 존재한다. 진행 로그와 결정 이유는 `docs/progress/` 에 시계열(순서·이유)로 기록한다(사용자 컨벤션). 파일명은 `underscore` 표기, `NN_제목.md` 형식(본 파일: `01_folder_structure_proposal.md`).

## 2. 제안 디렉터리 트리

```
AgentBrowser/
├── src/                          # [사실] 확장 프로그램 소스코드 루트
│   ├── extension/                # [사실] 브라우저 익스텐션 진입 계층 (MV3 명세 대응)
│   │   ├── content_script/       # [사실] 웹 페이지에 주입되는 Content Script
│   │   └── background/           # [사실] MV3 Service Worker (이벤트·메시지 라우팅)
│   ├── core/                     # [권고] 순수 비즈니스 로직 / 도메인 코어
│   │   ├── browser/              # [권고] 탭·윈도우 제어 추상화
│   │   ├── llm/                  # [권고] LLM 호출·프롬프트·응답 파싱
│   │   └── orchestrator/         # [권고] 에이전트/도구 실행 흐름 조율
│   └── agent/                    # [권고] 에이전트 정의 · 툴 · 실행 루프
│       ├── tools/                # [권고] 에이전트 호출 가능 액션 구현
│       ├── prompts/              # [권고] 시스템 프롬프트 템플릿
│       └── runner/               # [권고] 에이전트 실행기·상태 관리
├── tests/                        # [사실] 자동화 테스트 루트 (src 구조 대응)
│   ├── unit/                     # [권고] 모듈 단위 테스트
│   └── integration/              # [권고] 확장 동작 통합 테스트
├── docs/                         # [사실] 프로젝트 문서 루트
│   ├── progress/                 # [사실] 의사결정 순서·이유 기록 (진행 로그)
│   └── reports/                  # [사실] 최종 리포트 보관 (본 문서)
├── config/                       # [사실] 빌드/런타임/환경 설정 루트
│   ├── manifest.json             # [권고] MV3 익스텐션 매니페스트
│   └── env.example              # [권고] 환경변수 샘플 템플릿
└── scripts/                      # [사실] 빌드·배포·유틸리티 스크립트 루트
    ├── build.sh                  # [권고] 프로덕션 번들 빌드
    └── setup.sh                  # [권고] 로컬 개발 환경 초기화
```

## 3. 항목별 1줄 설명 (한국어)

- `src/` — 확장 프로그램의 모든 소스코드 루트.
- `src/extension/` — 익스텐션 진입 계층으로 CS·Background를 묶는 컨테이너.
- `src/extension/content_script/` — 웹 페이지에 주입되어 DOM·상호작용을 처리하는 스크립트.
- `src/extension/background/` — 메시지 라우팅·라이프사이클을 담당하는 MV3 Service Worker.
- `src/core/` — UI/익스텐션 의존성 없는 순수 비즈니스 로직 코어.
- `src/core/browser/` — 브라우저 탭·윈도우 제어를 추상화하는 모듈.
- `src/core/llm/` — LLM 호출, 프롬프트 구성, 응답 파싱 모듈.
- `src/core/orchestrator/` — 에이전트/도구 실행 흐름을 조율하는 오케스트레이터.
- `src/agent/` — 에이전트 규격, 도구, 실행 루프를 정의하는 계층.
- `src/agent/tools/` — 에이전트가 호출 가능한 액션/도구 구현.
- `src/agent/prompts/` — 에이전트 시스템 프롬프트 템플릿 보관.
- `src/agent/runner/` — 에이전트 실행기 및 상태 관리 로직.
- `tests/` — `src` 구조에 대응하는 자동화 테스트 루트.
- `tests/unit/` — 개별 모듈 단위 테스트.
- `tests/integration/` — 익스텐션 동작 통합 테스트.
- `docs/` — 프로젝트 문서 루트.
- `docs/progress/` — "왜·언제" 결정했는지 순서대로 기록하는 진행 로그.
- `docs/reports/` — 확정된 최종 리포트 보관소(컨벤션 준수).
- `config/` — 빌드/런타임/환경 설정 파일 루트.
- `config/manifest.json` — MV3 익스텐션 매니페스트.
- `config/env.example` — 환경변수 샘플 템플릿.
- `scripts/` — 빌드·배포·세팅 유틸리티 스크립트 루트.
- `scripts/build.sh` — 프로덕션 번들 빌드 스크립트.
- `scripts/setup.sh` — 로컬 개발 환경 초기화 스크립트.

## 4. evidence 기반 근거

### 4.1 인-리포지토리 증거 (사실, 본 세션 검증 완료)

- `IDEA.md` §4 "구현 경로(익스텐션)": 크롬 익스텐션(Content Script + Background)으로 구현한다. → `src/extension/content_script/`, `src/extension/background/` 분리의 직접 근거.
- `IDEA.md` §6 리스크 "익스텐션 MV3 제약": Manifest V3의 백그라운드 수명·API 제한이 장시간 세션 유지 설계에 영향. → background를 서비스 워커 단위로 격리하는 사실적 근거.
- `IDEA.md` §4 봇 탐지 회피 책임 분리: 익스텐션 자체는 `navigator.webdriver` 등으로 탐지될 수 있어 회피 목적이 아님. → extension 계층을 공유 세션·핸드오프·협업 UI 전용으로 한정하는 사실적 근거.
- `IDEA.md` §3 R3(인간→에이전트 핸드오프), R4(DOM 추출·저장), §5 액션스페이스·상태전이 프로토콜·에러복구 → `src/core`, `src/agent` 계층 존재의 권고 근거.

### 4.2 외부 표준 레이아웃 참조 (권고, canonical URL)

> 한계 명시: 본 세션에서 `web_search`/`web_extract` 백엔드(SearXNG)가 도달 불가하여 실시간 인출을 수행하지 못했다. 아래는 확립된 canonical 문서 URL을 근거로 제시하며, 추후 live 검증을 권고한다.

- Chrome for Developers, Manifest V3 — `https://developer.chrome.com/docs/extensions/mv3/` : content script와 background service worker를 익스텐션의 분리 구성요소로 명세.
- Chrome for Developers, Content Scripts — `https://developer.chrome.com/docs/extensions/mv3/content_scripts/`
- Chrome for Developers, Service Workers — `https://developer.chrome.com/docs/extensions/mv3/service_workers/`
- Playwright 공식 — `https://playwright.dev/` : `tests/` 폴더 및 루트 config 관행. → `tests/`, `config/` 분리 권고 근거.
- Puppeteer 공식 — `https://pptr.dev/` : 스크립트·예제·config 중심 구조. → `scripts/` 분리 권고 근거.

### 4.3 사실/권고 구분표

- **[사실]** 요구사항 #3 스켈레톤(`src/extension(content_script+background)`·`core`·`agent`, `tests/`, `docs/{progress,reports}`, `config/`, `scripts/`), `docs` 컨벤션, `IDEA.md` 파생 항목.
- **[권고]** `src/core`·`src/agent` 내부 세부 폴더, `tests/unit`·`integration`, `config/manifest.json`·`env.example`, `scripts/*.sh` — evidence 기반 권장이나 필수 아님.

### 4.4 반대 증거 및 주의사항 (Analyst R01)

- [권고] Playwright·Puppeteer는 Node 기반 자동화 라이브러리이지 브라우저 익스텐션이 아니다. 따라서 이들의 `tests/`, `config/`, `scripts/` 관행만 차용하고, `src` 내부 레이아웃(CS/Background 분리)은 이들의 구조가 아닌 MV3 명세를 근거로 한다. 즉 익스텐션 CS/Background 분리는 외부 라이브러리 증거로는 뒷받침되지 않으며, 전적으로 `IDEA.md` §4와 MV3 표준에 의존한다.
- [사실] MV3의 background는 영속 백그라운드 페이지가 아니라 이벤트 기반 Service Worker다. 장시간 세션 유지를 목표로 하는 AgentBrowser의 경우 `IDEA.md` §6이 지적한 백그라운드 수명 제약을 설계 단계에서 반영해야 한다.
- [사실] `docs/progress/` 디렉터리는 본 작성 시점에 아직 존재하지 않는다(파일시스템 확인 완료). 첫 의사결정 기록 시 생성하여 컨벤션을 실제로 적용해야 한다.

## 5. 적용 참고

- 신규 문서는 `docs/reports/NN_제목.md` 규칙을 따른다(본 문서는 `01_`).
- 결정 경위는 `docs/progress/` 에 타임라인 순으로 기록한다.
- `src` 하위 3계층(익스텐션 CS/Background · core · agent)은 책임 분리 원칙에 따라 독립 유지한다.
- [권고] `src/extension/` 을 컨테이너로 두어 CS와 Background를 한 묶음으로 응집시킨다. 이는 요구사항 #3의 "익스텐션: content_script + background" 그룹핑을 트리에 그대로 반영한 것이다.
- [권고] `core`/`agent` 내부 세부 폴더는 v1 범위(단일 확장 MVP)에서 비대해지지 않도록 최소한으로 시작하고, 책임이 명확해지면 분리한다.
- [사실] 본 제안서는 오직 `docs/reports/01_folder_structure_proposal.md` 한 파일만 수정하며, 다른 파일은 건드리지 않는다(작업 지시 준수).
- [권고] 본 제안 채택 여부는 `docs/progress/` 에 결정 근거와 함께 기록하고, 확정 시 본 리포트가 폴더 구조의 최종 기준이 된다.

## 6. 버전 이력

- **v1 (2026-08-12):** 초안. `cs_background` 명칭 사용, evidence/사실·권고 미분리, 외부 출처 미명시.
- **v2 (2026-08-12):** 요구사항 #3 스켈레톤(`extension/content_script + background`)으로 정렬, `IDEA.md`·MV3 표준 evidence 추가, `[사실]`/`[권고]` 표기 도입, 컨벤션 명시, 버전 이력 기록.
