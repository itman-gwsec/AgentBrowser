# 폴더 구조 제안 수락 (2026-08-12)
## 결정
docs/reports/01_folder_structure_proposal.md(v2) 제안을 수락하고 실제 디렉터리/파일 스켈레톤을 생성함.
## 근거
- 사용자 컨벤션 준수(docs/progress=의사결정, docs/reports=최종)
- IDEA.md §4 익스텐션 구현 경로(CS+Background) 반영
- Chrome MV3 표준 레이아웃 차용
## 적용 범위
- src/(extension/core/agent), tests/, docs/{progress,reports}, config/, scripts/ 생성
- config/manifest.json(MV3), env.example, scripts/build.sh/setup.sh 스텁 생성
