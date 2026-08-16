# 개발 원칙 확정: TDD + ruff 클린 100% + pydantic (2026-08-13)

## 결정
AgentBrowser 모든 코드 변경에 대해 다음 4원칙을 프로젝트 확정 규칙으로 채택한다.
1. **TDD** — 기능 구현 전 테스트 작성.
2. **ruff 클린 100%** — `ruff check` 에러 0건 유지.
3. **pydantic v2 모델 일원화** — 데이터 구조는 pydantic 모델로 표준화.
4. **OOP 표준** — 캡슐화·타입힌트·logger 일관성 준수.

위 원칙을 `.hermes.md` 컨벤션에 영구 기록한다.

## 근거(사실)
- [사실] 사전 실측: `tests/` 디렉터리에 `.gitkeep`만 존재(실제 테스트 0건). `ruff check src` 실행 결과 23 errors(UP045×7, BLE001×5, UP037×4, I001×2, DTZ005×1, RUF×3, TRY×2). `pyproject.toml` 없음(툴 설정 미정의). pydantic은 `handoff.py`만 사용, 타 모듈 미적용.
- [사실] OOP/구조 문제: orchestrator에 `print()` 디버그 노출, `datetime.now()` tz 누락, `runner.run()` 내부 CDP 미결선(책임 불일치), `manifest.json` 경로(`background/service_worker.js`)와 실제 파일(`background/background.js`) 불일치로 익스텐션 로드 블로커.
- [반대증거] 엄격 적용 시 초기 공수 증가(재구조화 약 7~9턴 추산) — 단 품질·유지보수 측면에서 정당.

## 적용
- 원칙 확정 및 `.hermes.md` 기록 완료.
- 이어서 재구조화 착수 순서: `pyproject.toml` 생성 → ruff 클린 → TDD 테스트 작성 → OOP 정리 → 구동 E2E.

## 버전/이력
- 2026-08-13: v1. 사용자 지시("TDD+ruff+pydantic 준수 기록") 직접 인용 기반.

## 참조
- `.hermes.md` (컨벤션 섹션, 개발 원칙 항목 추가)
- `ruff check src` 실측 결과(23 errors)
