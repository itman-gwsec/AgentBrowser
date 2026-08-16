# 15. LLM 연구 분석 보고서 파이프라인 (에이전트 브라우저 활용)

## §1. 목적
개발된 에이전트 전용 브라우저(실제 Chrome + 인간행동 시뮬레이션)를 **서브에이전트가
직접 검색**에 사용하여, 현시점 최신 LLM 모델 연구 10건을 선정·분석한 보고서를
작성하고 이메일로 송부하는 파이프라인을 검증한다. 사용자 지시(2026-08-15):
"검색은 복수 에이전트가 수행하면 안 되며 **단일 에이전트가 수행**해야 한다.
나머지(선정·분석·보고서)는 **복수 검토로 신뢰도·품질 향상**."

## §2. 파이프라인 구성
- **Phase A (단일 에이전트)**: 증거 수집 독점. `agent_search_llm_research.py`로
  10쿼리 실제 브라우저 검색(DDG/Bing, 구글 제외) → 183건 증거풀.
- **Phase B (복수 에이전트)**:
  - 선정 A (수치/신뢰도 관점) + 선정 B (산업임팩트 관점) 독립 선정
  - Critic (편향/근거부족/누락/신뢰도 지적) + Validator (URL 실존·신뢰도 크로스체크)
  - Synthesizer (A/B/Critic/Validator 종합 → 최종 10건 합의)
- **Phase C (복수 에이전트)**: Writer (초안) + Editor (구조/논리/과장 검토) →
  Sender (Google Workspace Gmail API 로 storysii@naver.com 송부).

## §3. 설계 결정 근거
- 검색 독점: 복수가 각자 검색하면 중복 수집·파싱 불일치 발생 → 증거 일관성 위해 단일화.
- 선정 복수화: 단일 선정 시 자기확증 편향 가능 → A/B 독립 + Critic/Validator로 편향 최소화.
- 구글 제외: 사용자 명시 지시 준수 (DDG/Bing 한정).

## §4. 검증 결과
- Phase A: 10쿼리 × 20건 = 200건 raw → 중복제거 183건 풀.
- Phase B: A/B 교집합 2건(DeepSeek-R1 등), Critic가 저신뢰 블로그 3건 교체 권고,
  Validator가 18건 실존·low_trust 5건 확인. 최종 10건 합의(고신뢰 6 + 중신뢰 4).
- Phase C: 보고서 `docs/reports/llm_research_analysis.md` 작성 → Editor 수정후승인
  (must_fix 1건: 신뢰도 건수 정정 → Botler가 직접 패치).
- **이메일 송부 실측 확인**: Gmail API Sent 폴더에서 Message ID `1a0037e35be18097`
  (To: storysii@naver.com) 존재 확인 — 실제 발송 증명.

## §5. 한계 및 차후 과제
- 증거풀은 DDG/Bing 한정(구글 제외 지시) → 구글 결과 누락 가능성.
- 모델비교 분야는 신뢰 출처 부재로 미포함(정보부족 유보).
- RAG/Llama3/MMBench 등은 증거풀 부재로 편입 불가.
- 실제 URL 본문 미열람 상태에서 제목+출처 기반 분석(과장 방지 명시).
- 이메일 발송용 임시 스크립트(`~/.hermes/send_report.py`)는 재송부용으로 잔존.
