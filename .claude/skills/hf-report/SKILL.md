---
name: hf-report
description: 기술 리포트(PDF/arXiv)가 있는 모델 중 README만으로 정보가 부족한 경우, 리포트를 섹션별로 잘라 필요한 부분만 읽어 벤치마크·모델 구축방식 등을 보강한다. "기술 리포트 확인해줘", "논문 봐서 벤치마크 채워줘" 요청에 사용. 최종 포함 확정 + 리포트 존재 + 정보 공백이 있을 때만 동작하는 최후 수단 단계.
---

# hf-report

## 언제 실행하는가 (전부 만족해야 함 — 토큰 낭비 방지)
1. `excluded: false` (이미 최종 엑셀 포함 확정된 모델)
2. `technical_report_url`이 존재
3. 2차(README 기반) AI 정제까지 끝냈는데도 여전히 중요한 정보가 비어있음 — 구체적으로: 벤치마크_* 6개가 전부 `null` **이거나** `construction_method`가 `null`

즉 README만으로 이미 다 채운 모델은 리포트가 있어도 절대 건드리지 않는다. 실제로 naver-hyperclovax/HyperCLOVAX-SEED-Omni-8B에서 이 단계가 벤치마크와 모델 구축방식(README로는 애매했지만 리포트엔 "pre-trained backbone을 SFT"라고 명시돼 있어 파인튜닝 모델로 정정됨) 둘 다 실제로 채운 것을 확인함.

## 토큰 최소화 구조: "다운로드+섹션분해"는 스크립트, AI는 섹션 하나만
1. `scripts/extract_report_sections.py`(결정론적, LLM 토큰 0)가 PDF를 다운로드해 전체 텍스트를 추출하고, "Abstract/Introduction/Method/Training/Evaluation/Results/Conclusion" 같은 제목으로 섹션을 나눠 캐시 JSON에 저장한다.
2. 이 에이전트는 그 JSON에서 **필요한 섹션 하나만** 읽는다 — 벤치마크가 필요하면 `Evaluation`/`Results`/`Benchmarks`, 모델 구축방식이 필요하면 `Method`/`Training`/`Post-Training`/`Model`. 논문 전체(수만 자)가 아니라 그 섹션(보통 수천~2만 자 이내)만 컨텍스트에 들어온다.
3. 채운 값은 `hf-refine`과 동일한 통제 어휘·형식 규칙을 따른다 (벤치마크 분류/0~100 스케일/모델 구축방식 9종 등 — `hf-refine` 스킬 참조).

## 스크립트 계약 (`scripts/extract_report_sections.py` — 구현 완료, 실제 PDF로 검증됨)
```
python scripts/extract_report_sections.py \
  --model-id naver-hyperclovax/HyperCLOVAX-SEED-Omni-8B \
  --report-url https://huggingface.co/.../resolve/main/HyperCLOVA_X_8B_Omni.pdf \
  --cache-dir <스크래치 또는 raw/report_cache>
# stdout: {"model_id":..., "sections_found": ["Abstract","Evaluation",...], "cache_path": "...", "cached": bool}
#      또는 {"model_id":..., "error": "..."} (exit 1) — PDF가 아니거나, 텍스트 추출량이 200자 미만(스캔본 추정)이면 실패로 처리하고 포기
```
- arXiv `abs` 링크는 자동으로 `pdf` 링크로 변환해서 받는다.
- 같은 model_id의 섹션 캐시가 이미 있으면 재다운로드하지 않는다(`cached: true`).
- **진짜 스캔 이미지 PDF(텍스트 추출 거의 안 됨)는 지금은 처리하지 않는다** — OCR(이미지→텍스트)까지 하려면 Tesseract 같은 시스템 바이너리가 추가로 필요해서 예약 실행 환경이 복잡해진다. 실패하면 그냥 포기하고 `null` 유지 (나중에 이런 사례가 많으면 그때 추가 검토).

## 에러 처리
- `technical_report_url`이 PDF가 아닌 임의 웹페이지(예: GitHub/블로그 링크)면 다운로드/파싱을 시도하지 않고 바로 포기 — 웹페이지 스크래핑은 이 스킬의 범위 밖.
- 다운로드 실패, 추출 텍스트 너무 짧음 등 어떤 이유로든 실패하면 해당 모델의 필드는 그대로 `null` 유지 — 파이프라인 전체를 막지 않는다.
