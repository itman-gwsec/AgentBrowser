# 구현 설계안 수락 및 MVP 착수 결정 (2026-08-12)

## 결정
docs/reports/02_implementation_design.md(v1)를 MVP 구현 가이드로 수락하고, 이후 src/ 에 실제 MVP 코드를 작성한다.

## 근거 (사실)
- [사실] IDEA.md §2는 MVP 경계를 "헤드풀 실제 크롬 브라우징, DOM 추출·저장, 인간→에이전트 위임 시나리오 1종"으로 명시하며, 설계안 §1이 이를 그대로 수용한다(양자 일치 확인).
- [사실] IDEA.md §6 리스크(헤드풀 성능 부하, MV3 백그라운드 수명·API 제한)는 설계안 §9에서 동시 세션 수 제한(헤드풀 성능)과 이벤트 기반 Service Worker 설계(MV3 수명)로 관리 가능함이 제시된다.
- [사실] 협업 UI(R5), 보안/샌드박싱, 법적 검토는 IDEA.md §2 후속 범위 및 설계안 §1 권고로 명시 분리되어 v1 범위 통제가 성립한다.
- [반대증거] 장시간 세션에 MV3 Service Worker 단독 사용은 수명 제약으로 난이도가 높아, Python bridge가 세션 상태를 보유하는 보완 설계가 필요하다(설계안 §9). 이는 리스크 완전 소멸이 아닌 완화임을 명시한다.

## 적용 순서
1. (b) 본 진행 로그 기록 — docs/progress/02_implementation_design_accepted.md 신규 작성.
2. (a) src/ 에 MVP 코드 작성: 익스텐션(Content Script / Background) + Python(core/agent) 스켈레톤, 핸드오프 스키마(pydantic), DOM 추출, HITL 흐름.

## 버전/이력
- 2026-08-12: v1 생성. 모든 근거는 IDEA.md(§2, §6) 및 docs/reports/02_implementation_design.md(v1, §1, §9) 직접 인용에 기반.

## 참조
- docs/reports/02_implementation_design.md
- docs/reports/01_folder_structure_proposal.md
- IDEA.md §2, §6
