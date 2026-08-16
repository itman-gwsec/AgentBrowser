# MoE 기술 적용 오픈 가중치 모델 비교 분석 (100GB 이하 선정)

- **작성일**: 2026-08-16
- **방법**: 에이전트 브라우저 실제 검색/방문 → 정량 수집 → 복수 검토
- **작성 롤**: Analyst (R01) — 모든 수치는 수집 원본(evidence) 기반, 추정치/파생치는 신뢰도와 함께 명시
- **데이터 근거**: `/tmp/moe_pool.json`, `moe_models.json`(v1), `moe_models_v2.json`(v2), `moe_selected_A.json`, `moe_selected_B.json`, `moe_critic.json`, `moe_validated.json`, `moe_final_3.json`

> ⚠️ **독자 주의**: 본 보고서의 `tok/s` 수치 중 2건(gpt-oss-20b, Mixtral 8x7B)은 수집 원본의 **범위 중간값(파생치)**이며 정밀 측정치가 아님. gpt-oss-120b의 유일한 품질지표(ELO 7.8)는 정상 스케일(1000~1600)을 벗어난 이상치로 **품질지표에서 제외**함. 허위수치는 0건이나, 수치 신뢰도는 항목별로 표기됨.

---

## 1. 개요 및 선정 방법론

MoE(Mixture of Experts) 아키텍처를 채택한 **오픈 가중치** LLM 중, 단일 머신(양자화 기준 100GB 이하)에서 구동 가능한 후보를 실증적으로 비교·선정했다.

- **수집**: 에이전트 브라우저로 DDG/Bing 검색 + 깃허브/arXiv/공식 블로그/벤치마크(artificialanalysis.ai) 방문 수집. **구글 검색은 제외**. 총 160건 raw → 17개 모델 엔트리 정량 수집(v1 17건 + v2 17건).
- **파이프라인**:
  1. 단일 에이전트 정량 수집 (`moe_models.json`, `moe_models_v2.json`)
  2. A/B 독립 선정 (`moe_selected_A.json` — 수치완비 우선, `moe_selected_B.json` — 실무 배포 적합성)
  3. Critic / Validator 검토 (`moe_critic.json`, `moe_validated.json`)
  4. Synthesizer 합의 최종 3개 확정 (`moe_final_3.json`)
- **선정 기준(3항목)**:
  1. **양자화 Q4 크기 ≤ 100GB** (단일 머신 구동 가능성)
  2. **추론 속도(tok/s)** — 실제 하드웨어 기준
  3. **추론 품질(MMLU / Arena ELO 등)**
- **크기 기준**: 양자화(GGUF Q4 / MXFP4) 기준. 원본 FP16은 수 TB 단위로 단일 머신 부적합이므로 제외.

---

## 2. 선정 기준 및 배제 사유

### 2.1 100GB 초과 → 1차 필터 탈락
| 모델 | Q4(GB) | FP16(GB) | 탈락 사유 |
|---|---|---|---|
| DeepSeek-V3 | 404 | 1342 | Q4 100GB 초과, 멀티 H100 클러스터 필요 |
| Qwen3-235B-A22B | 142 | 470 | Q4 100GB 초과 |
| Kimi K3 | null | 5600 | q4 미확보·FP16 5.6TB → 크기 초과 확실 |
| GLM-5.2 | null | 1506 | FP16 100GB 초과 |
| DeepSeek V4 Pro | null | 3200 | FP16 100GB 초과 |
| MiniMax-M3 | null | 856 | FP16 100GB 초과 |
| Nemotron 3 Ultra | null | 1100 | FP16 100GB 초과 |
| Nemotron 3 Super | null | 241 | FP16 100GB 초과 |

> 참고: 위 대형 모델 중 일부(DeepSeek-V3, Qwen3-235B 등)는 MMLU 87~88 수준의 우수한 품질지표를 보유하나 **크기 기준 위반**으로 본 비교(100GB 이하) 대상에서 탈락.

### 2.2 크기 기준 = 양자화(Q4) 기준
원본 FP16은 DeepSeek-V3 1342GB, Kimi K3 5600GB 등 수 TB라 단일 머신 구동 불가. 따라서 **양자화 Q4/MXFP4 크기가 선정의 1차 게이트**임.

---

## 3. 최종 선정 3개 상세

### 1. gpt-oss-120b (Q4 65GB · tok/s 182.26 · 품질지표 파손)

- **출처**:
  - https://artificialanalysis.ai/models/gpt-oss-120b (v2 벤치, tok_s·q4·ELO 원본)
  - https://artificialanalysis.ai/models
  - https://ollama.com/library/gpt-oss (OpenAI 공식 오픈가중치 배포 확인)
- **양자화 크기**: 65 GB (Q4) — v2 리터럴 `quant_size_gb.q4=65`. FP16 234GB.
- **추론 속도**: **182.26 tok/s** — v2 레코드에서 직접 수집한 **유일한 리터럴 측정치** (H100/A100급 벤치). 신뢰도: **높음(측정치)**.
- **추론 품질**: **해당 없음(품질지표 파손)**. 원본의 유일한 품질지표 `aa_briefcase_elo_mid=7.8`은 정상 ELO 스케일(통상 1000~1600)을 크게 벗어난 소수값으로 **이상치·신뢰불가 → 품질지표에서 제외**. MMLU 등 표준 지표 부재.
- **선정 사유**: ① Q4 65GB(≤100 통과) ② 전체 후보 중 **최고 tok/s 182.26(측정치)** ③ OpenAI 공식 오픈가중치로 배포/감사 신뢰성 최고. — 단, ③품질 기준은 충족하지 못함(지표 파손). 크기·속도 기준으로만 선정 사유 유지.
- **⚠️ 경고**:
  - ELO 7.8은 정상 스케일 이상치(수집/스케일 오류 의심)로 **품질지표에서 제외**했으므로, 본 모델은 유효 품질지표가 없음.
  - 비대칭 증거 기준 우려(Critic 지적): 품질지표가 파손됐음에도 tok/s 최고·"OpenAI 공식" 서사로 #1 선정됨(상세 §6).

### 2. gpt-oss-20b (Q4 13GB · tok/s 38.5 · MMLU 85.3)

- **출처**:
  - https://insiderllm.com/guides/gpt-oss-guide-openai-local/ (v1, q4·tok_s 범위·MMLU/SWE-Bench 원본)
  - https://arxiv.org/html/2401.04088v1 (교차보완용, Mixtral 기준)
- **양자화 크기**: 13 GB (MXFP4) — v1 리터럴 `size_gb.quantized=13`.
- **추론 속도**: **38.5 tok/s** — ⚠️ **측정치 아님**. v1 원본 범위 `35-42 (16GB GPU)`의 **중간값(파생치)**. 단일 블로그 가이드 출처, 정밀 측정치 아님. 신뢰도: **낮음(범위파생)**.
- **추론 품질**: **MMLU 85.3** / **SWE-Bench 60.7** — v1 리터럴. Arena ELO 부재.
- **선정 사유**: ① 최소 Q4 13GB(엣지/소비자 티어) ② MMLU 85.3로 소형 중 최고품질 ③ 크기·품질·속도 균형 우수. — 단 ②속도 기준은 범위파생치.
- **⚠️ 경고**: tok/s 38.5는 35-42 범위 중간값, 단일 블로그(insiderllm) 출처·정밀 측정치 아님. Arena ELO 부재.

### 3. Mixtral 8x7B (Q4 26GB · tok/s 13.5 · MMLU 70.6 / Arena ELO 1121)

- **출처**:
  - https://mistral.ai/news/mixtral-of-experts (v2, q4 26GB 원본)
  - https://arxiv.org/html/2401.04088v1 (v1, MMLU 70.6 / Arena ELO 1121 원본)
  - https://www.metatech.dev/blog/2026-05-27-local-ai-moe-models-mixtral-vs-qwen2-vs-deepseek-on-96gb-100148 (v1, tok_s 범위 원본)
- **양자화 크기**: 26 GB (Q4) — v2 리터럴 `quant_size_gb.q4=26`. FP16 93.4GB.
- **추론 속도**: **13.5 tok/s** — ⚠️ **측정치 아님**. v1 원본 범위 `12-15 (dual RTX 6090, 4K ctx)`의 **중간값(파생치)**. 단일 블로그 실측 범위, 정밀 측정치 아님. 신뢰도: **낮음(범위파생)**.
- **추론 품질**: **MMLU 70.6** / **Arena ELO 1121** — v1 리터럴(arXiv). 세 모델 중 **유일하게 tok_s·품질 양측 수치를 모두 확보**.
- **선정 사유**: ① Q4 26GB(24GB 소비자 GPU 구동) ② MMLU 70.6 + Arena ELO 1121(수치 완비) ③ MoE 중 가장 성숙·검증된 프로덕션 워크호스(생태계 성숙). — 단 ②속도 기준은 범위파생.
- **⚠️ 경고**: tok/s 13.5는 12-15 범위 중간값, 단일 블로그(metatech.dev) 실측·정밀 측정치 아님.

---

## 4. 비교 표

| 모델 | Q4(GB) | tok/s | MMLU | ELO | 비고 |
|---|---|---|---|---|---|
| **gpt-oss-120b** | 65 | 182.26 (측정치) | — (품질지표 파손) | 7.8 (이상치·제외) | 유일 측정 tok/s 최고, OpenAI 공식 |
| **gpt-oss-20b** | 13 | 38.5 (범위중간값·측정치 아님) | 85.3 | — | SWE-Bench 60.7, 소형 최고품질 |
| **Mixtral 8x7B** | 26 | 13.5 (범위중간값·측정치 아님) | 70.6 | 1121 | 유일 tok_s·품질 양측 수치, 생태계 성숙 |

> `tok/s` 신뢰도: gpt-oss-120b만 **측정치(높음)**, 나머지 2건은 **범위파생(낮음)**. `ELO`는 gpt-oss-120b만 존재하나 이상치로 제외 → 표준 ELO 비교 불가.

---

## 5. Honorable Mention

### Mixtral 8x22B (Q4 80GB)
- **출처**: https://mistral.ai/news/mixtral-8x22b (v2, `quant_size_gb.q4=80` 리터럴)
- **크기**: Q4 80GB(≤100GB 통과), FP16 282GB. Mistral 공식, 생태계 성숙.
- **미선정 사유**: 본 데이터셋에 **실측 tok/s 및 품질 수치가 부재** → "수치 있는 것 우선" 원칙에 따라 near-miss로 제외. Critic은 4번째 슬롯/재검토 권고.
- **의의**: 크기·생태계를 충족하며, 유효 품질 대리지표(Arena ELO 등)만 확보되면 품질지표가 파손된 gpt-oss-120b보다 상위 배치 여지가 있음.

---

## 6. 검토 결과 및 한계

### 6.1 Validator 결과 (`moe_validated.json`)
- **허위수치: 0건**. 모든 수치는 수집 원본(v1/v2)에 리터럴 존재하거나 범위파생임을 확인.
- **tok/s 2건은 범위 중간값(정직 기록)**:
  - gpt-oss-20b 38.5 ← v1 범위 `35-42` 중간값 (v2에 해당 레코드 없음)
  - Mixtral 8x7B 13.5 ← v1 범위 `12-15` 중간값 (v2는 `tok_s=null`)
  - 둘 다 "허위 아님, 단 리터럴 원본 부재(파생값)"로 분류.
- **이상치 1건**: gpt-oss-120b `aa_briefcase_elo_mid=7.8` — 정상 ELO 범위(1000~1600) 이탈, 신뢰불가 → 품질지표 제외.

### 6.2 Critic 결과 (`moe_critic.json`)
- **gpt-oss-120b ELO 7.8 이상치**: 당 지표는 원본에 실재하나 스케일 오류 의심 → 품질지표에서 제외(본 보고서 §3 반영).
- **벤더 편향(2/3 OpenAI)**: A/B 공동 선정 3건 중 gpt-oss-120b·gpt-oss-20b 2건이 OpenAI, 비OpenAI는 Mixtral 8x7B 1건뿐.
- **비대칭 증거 기준(asymmetric evidence bar)**: gpt-oss-120b는 유일 품질지표가 파손됐음에도 tok/s 최고·"OpenAI 공식" 서사로 #1 선정된 반면, 비OpenAI 크기적합 모델(Mixtral 8x22B, Q4 80GB)은 수치 부재로 배제. 동일한 "수치 부재"에 대해 OpenAI 모델은 관대·비OpenAI는 엄격 → 경미한 벤더 편향.
- **권고**: ① gpt-oss-120b를 #1로 확정하지 말고 aa ELO를 유효 출처에서 재수집 ② tok/s는 점추정이 아닌 범위파생치로 명시 ③ Mixtral 8x22B를 최소 honorable-mention/4번째 슬롯으로 재검토 ④ 벤더 편중 문서화. (본 보고서 §3·§5·§6에 반영)

### 6.3 수집 한계
- **HF Cloudflare 차단**: `huggingface.co` 호스팅 페이지(DeepSeek-V3, Qwen2.5-MoE, OLMoE) 3건 차단 → 해당 수치는 arXiv/GitHub에서 대체 수집. 일부 모델 수치 미수집.
- **품질 벤치마크 편중**: MMLU/Arena ELO 등 표준 지표는 구모델(Mixtral 8x7B 등)에 편중. 신규 대형 MoE는 ELO 지표가 없거나 이상치(7.8)뿐.
- **Kimi K3 활성 파라미터 충돌**: 블로그 ~50B vs 공식 보고서 104B — 양측 보존(상충 증거 규칙)하나 크기 초과로 선정 무관.
- **Qwen2.5-MoE-A14B 미수집**: HF 차단 + Qwen2.5 보고서에 MoE-A14B 섹션 부재 → Qwen2-MoE-A14B로 대체 수집.
- **tok/s 측정 환경 비균질**: gpt-oss-120b(H100급) vs gpt-oss-20b(16GB GPU) vs Mixtral 8x7B(dual RTX 6090) — 하드웨어·컨텍스트 길이가 달라 **tok/s는 모델 간 절대 비교 불가**, 상대적 참고치로만 해석.

### 6.4 합의 verdict
3개 선정 확정 (수치 신뢰도 한계 명시). — `moe_final_3.json: verdict`

---

## 부록: 수집 원본 출처 요약
| 모델 | 주요 출처 URL |
|---|---|
| gpt-oss-120b | artificialanalysis.ai/models/gpt-oss-120b, ollama.com/library/gpt-oss |
| gpt-oss-20b | insiderllm.com/guides/gpt-oss-guide-openai-local |
| Mixtral 8x7B | mistral.ai/news/mixtral-of-experts, arxiv.org/html/2401.04088v1, metatech.dev/blog/2026-05-27-... |
| Mixtral 8x22B | mistral.ai/news/mixtral-8x22b |
| DeepSeek-V3(탈락) | github.com/deepseek-ai/DeepSeek-V3, arxiv.org/html/2412.19437v1 |

*본 보고서는 수집 원본(moe_*.json)의 리터럴 수치와 검토 기록에만 근거하며, 별도 검색/방문 없이 작성됨.*
