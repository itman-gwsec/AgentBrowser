# 12. Phase4 구현 — 정밀도·자율성 보강

> 롤: analyst (R01) — 모든 주장은 실측/소스 기반 evidence 로 뒷받침.
> 작성 근거: `src/core/search.py`, `src/extension/manifest.json`, `scripts/build_extension.sh`, 단위테스트, 로컬 실행 결과(pytest 56 passed, ruff 클린, zip 생성, manifest JSON 파싱).

## §1. 목적

Phase3에서 완성한 에이전트 전용 브라우저(LLM 연동·결과 파싱·배너 UI·세션 학습·resume)의 **정밀도**와 **자율성**을 보강한다.
직접 동기가 된 사용자 요구는 "검색 실패 → 신뢰도 하락 방지"의 연장선이다. 구체적으로 세 가지를 보강한다.

1. 장기 패턴(중복 쿼리)을 동적 가중치 피드백으로 연결해, 반복 탐색일수록 인간처럼 지연 행동하도록 한다.
2. 엔진별 결과 구조 차이를 정밀 selector 로 대응해, 파싱 누락·광고 노이즈를 줄인다.
3. 익스텐션 빌드를 스크립트로 자동화해, 배포 산출물 생성을 재현 가능하게 만든다.

## §2. 구현 범위

- ① 동적 가중치 피드백 (장기 패턴 → engine_weights 보정)
- ② 엔진별 정밀 파싱 (엔진별 `_RESULT_SELECTOR` 분기 + fallback)
- ③ 익스텐션 빌드 자동화 (manifest + `build_extension.sh`)

## §3. 각 항목 명세 (1줄)

- ① `SearchDispatcher._compute_dynamic_weights()` 가 `SessionLog.duplicate_query_ratio(window=20)` 기반으로 `factor = 1.0 + min(dup_ratio, 0.5) * 0.6`(상한 2.0)을 산출하고, `run()` 진입 시 `config.model_copy(update={"engine_weights": dynamic})` 로 적용한다.
- ② `SearchEngine._RESULT_SELECTOR` 클래스변수를 엔진별로 정의(google=`div.g a h3, #search a h3, div.g a` / ddg=`a[data-testid="result-title-a"], a.result__a` / bing=`li.b_algo h2 a`)하고, `_extract_links` 가 셀렉터 분기 후 0건이면 범용 `a[href]` fallback 으로 재시도한다.
- ③ `src/extension/manifest.json`(MV3, v0.4.0, 권한 `activeTab`/`scripting`/`storage` 최소화)을 `scripts/build_extension.sh` 가 `builds/` 로 복사 후 zip 패키징(`builds/agentbrowser_extension.zip`, 5723B 확인)한다.

## §4. 검증

- ruff 클린: 커밋 대상 5개 파일 기준 0 오류(전체 스캔 3오류는 제외 대상 `scripts/test_qwen_search.py` 에 한정).
- pytest: `56 passed` (단위테스트 `tests/unit/test_search.py` 포함).
- 빌드: `bash scripts/build_extension.sh` 실행 → `builds/agentbrowser_extension.zip` 생성 확인(5723B).
- manifest: `json.load` 파싱 통과, `manifest_version=3`, `version=0.4.0`, `permissions=[activeTab, scripting, storage]` 확인.

## §5. 차후 과제

- 실제 LLM 키 연동 E2E 검증 (현재 키 미사용 — 단위테스트만 통과).
- 엔진별 selector 의 실브라우저 검증 (현재는 단위테스트/모의 DOM 기반).
- 장기 패턴 기반 더 정교한 보정 (쿼리 간격·엔진 선호도 가중 추가).
- 익스텐션 자동 로드 (launcher 와 통합해 빌드→로드 단계 연결).
