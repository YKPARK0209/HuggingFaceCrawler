---
name: hf-refine
description: 크롤링된 raw Hugging Face 모델 데이터를 결정론적 규칙(1차)과 AI(2차, 신규/업데이트분 한정)로 정제해 마스터 데이터셋(data/master_dataset.jsonl)에 반영한다. "정제해줘", "엑셀에 넣을 데이터 정리", "모델 설명 요약/번역해줘", "마스터 데이터셋 갱신" 요청에 사용. 이 파이프라인에서 LLM이 실제로 판단하는 유일한 단계다.
---

# hf-refine

## 두 단계로 나뉜 이유
- **1차(결정론적, `scripts/refine.py`)**: 다운로드 수, 라이선스, 태그처럼 API 응답에서 그대로 뽑을 수 있는 값. 규칙만 있으면 되므로 AI가 필요 없고, AI가 하면 오히려 토큰 낭비 + 일관성 저하.
- **2차(AI, 이 스킬을 쓰는 에이전트가 직접 수행)**: 자연어 판단이 필요한 것 — 예: README를 한글로 요약/번역, 내용을 정리. **정확히 무엇을 하는지는 아직 확정되지 않았다.**

## ⚠️ 현재 상태: 두 가지 모두 TBD (미확정) — 임의로 채우지 말 것
1. **1차 정제 규칙과 마스터 스키마(엑셀 컬럼 구성)**: 사용자가 첫 실제 크롤링 결과(`raw/`)를 함께 보고 확정하기로 했다. 확정 전에는 §후보 필드 절의 필드들을 임시로 그대로 옮기는 정도로만 구현하고, 확정되면 이 문서와 `scripts/refine.py`를 함께 갱신한다.
2. **2차 AI 정제의 정확한 작업 내용**: 요약인지, 번역인지, 다른 정리인지 사용자가 별도로 지시하기로 했다. 지시받기 전에는 `pending_ai_inputs.json`의 항목을 과도하게 가공하지 말고, 최소 처리(예: 있는 그대로 통과)만 하거나 명시적으로 "아직 미정"이라고 표시해 둔다. 지시가 오면 이 문서의 "2차 정제 작업 정의" 절을 채운다.

## 후보 필드 (§ HF API에서 확인된 것 — 최종 스키마 아님)
`model_id, org, display_name, pipeline_tag, license, downloads, likes, tags[], parameters(safetensors), used_storage, sha, created_at, last_modified, url, first_seen_at, last_refined_at` + (2차 정제 결과가 채울) AI 관련 필드 1개 이상.

## state 없는 필드 관리 원칙
`downloads`/`likes`처럼 항상 변하는 값은 매번 마스터 데이터셋에 최신값으로 덮어쓴다(diff 판별에는 안 쓰지만 엑셀에는 최신값이 보여야 하므로).

## 스크립트 계약 (아직 미구현)
```
python scripts/refine.py \
  --raw-dir raw/ --companies-file data/companies.json \
  --master-file data/master_dataset.jsonl --changes-out logs/last_run_changes.json
# stdout: {"upserted":N,"pending_ai":N}
# 부가 출력: logs/pending_ai_inputs.json  ([{model_id, readme_excerpt, ...}, ...])

python scripts/merge_ai_summaries.py \
  --ai-outputs logs/ai_outputs.json --master-file data/master_dataset.jsonl
# ai_outputs.json이 없거나 비어있으면 no-op으로 안전 종료(exit 0)
```

## 마스터 데이터셋 형식: JSONL (확정)
한 줄 = 모델 하나, `model_id` 기준 upsert. SQLite는 git diff 불가/병합 불가라 제외, CSV는 `tags` 같은 리스트 필드 처리가 번거로워 제외 — JSONL이 `git diff`로 리뷰 가능하면서 `pd.read_json(lines=True)`로 바로 로드된다.

## AI 정제(2차) 실행 방법 — 확정 전 임시 절차
1. `logs/pending_ai_inputs.json`이 비어있으면 **이 절 전체를 건너뛴다** (토큰 0 사용 — 파이프라인 핵심 비용 절감 지점이므로 반드시 지킬 것).
2. 비어있지 않으면 내용을 읽고, 이 문서의 "2차 정제 작업 정의"가 아직 비어있다면 각 항목을 최소 가공(원문 그대로 또는 단순 정리)해서 `logs/ai_outputs.json`에 쓴다.
3. 작업 정의가 채워지면 그 지시를 따른다.

### 2차 정제 작업 정의 (사용자 지시 대기 중 — 비어있음)
<!-- 사용자가 2차 정제 스펙(요약/번역/정리 등)을 확정하면 여기에 구체적으로 기술한다 -->
