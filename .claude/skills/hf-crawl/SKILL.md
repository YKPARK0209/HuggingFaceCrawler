---
name: hf-crawl
description: Hugging Face Hub API로 회사(organization)별 모델 목록/메타데이터/README를 수집하고 이전 크롤링 대비 신규(new)/업데이트(updated)/무변경(unchanged)/삭제(removed) 모델을 판별한다. "허깅페이스 크롤링해줘", "새로 나온 모델 확인", "회사 목록에 추가/삭제", "특정 회사만 다시 크롤링" 같은 요청에 반드시 사용한다. hf-pipeline 오케스트레이터의 1단계로도 쓰이고, 단독으로 특정 회사만 재크롤링할 때도 쓴다.
---

# hf-crawl

## 언제 이 스킬을 쓰는가
- 정기 크롤링(예약 실행 또는 수동 `/hf-pipeline`)의 1단계
- 사용자가 "회사 목록에 X 추가해줘" → `data/companies.json`에 추가 후 해당 회사만 크롤링해서 정상 동작 확인
- 사용자가 "이 회사만 강제로 전체 재크롤링" → `--org` 옵션으로 단독 실행

## 핵심 원리: state 기반 diff로 API 호출을 최소화한다
회사별 상태 파일 `state/<org>.json`에 마지막으로 본 각 모델의 `sha`(HF 저장소 커밋 해시)를 저장해두고, 이번 크롤링 결과와 비교한다. **`sha`가 변경 감지의 유일한 신뢰 가능한 신호다** — 파일이 하나라도 바뀌면 반드시 달라지기 때문. `downloads`/`likes`처럼 항상 변하는 값은 diff 기준에 넣지 않는다(넣으면 매번 모든 모델이 "업데이트"로 오탐된다).

| 조건 | 분류 |
|---|---|
| state에 없음 (또는 이전 status가 removed) | **new** |
| state에 있고 `sha` 다름 | **updated** |
| state에 있고 `sha` 같음 | **unchanged** — 상세 재조회 안 함 |
| state에 active로 있었는데 이번 목록에 없음 | **removed** — 항목은 지우지 않고 status만 변경(이력 보존) |

new/updated로 분류된 모델만 상세 정보(전체 메타데이터 + README 원문)를 추가로 가져온다. unchanged는 목록 조회 시 받은 `sha`/`lastModified` 갱신 외에는 아무것도 더 하지 않는다.

## state 파일 스키마
`state/<org>.json`:
```json
{
  "org": "naver-hyperclovax",
  "last_crawled_at": "2026-07-20T00:00:00Z",
  "models": {
    "naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-0.5B": {
      "sha": "3da5046fb0195d14f2497de198136987d35fd644",
      "last_modified": "2025-07-21T15:13:41.000Z",
      "status": "active",
      "first_seen_at": "2026-06-01T03:00:12Z",
      "last_seen_at": "2026-07-20T00:00:00Z",
      "removed_at": null
    }
  }
}
```

## HF Hub API로 얻을 수 있는 필드 (실제 호출로 확인됨)
`GET https://huggingface.co/api/models/{id}` 응답: `id/modelId, author, sha, createdAt, lastModified, private, gated, disabled, downloads, likes, pipeline_tag, library_name, tags[], cardData{license, license_name, ...}, config, transformersInfo, siblings[](파일 목록), safetensors.parameters, usedStorage, spaces[], model-index`.
README 원문은 별도 요청 필요: `https://huggingface.co/{id}/raw/main/README.md` (또는 `huggingface_hub.hf_hub_download`).
new/updated 모델에 대해서는 **이 필드들을 대부분 트리밍 없이 raw로 저장**한다 — 정제(hf-refine) 단계에서 무엇을 쓸지 나중에 고르므로, 크롤링 단계에서 미리 줄이지 않는다.

## 스크립트 계약 (`scripts/crawl.py` — 아직 미구현)
```
python scripts/crawl.py \
  --companies-file data/companies.json \
  --state-dir state/ \
  --raw-dir raw/ \
  --log-file logs/run_log.jsonl \
  [--org <slug>]
```
- 출력: `raw/<org>/<model_id_sanitized>.json` (슬래시는 `__`로 치환), `state/<org>.json` 갱신, `logs/run_log.jsonl`에 한 줄 append
- stdout 마지막 줄(다른 무엇도 출력하지 말 것 — 오케스트레이터가 이 한 줄만 읽는다): `{"new":N,"updated":N,"unchanged":N,"removed":N,"errors":["org: message", ...]}`
- 인증: `HF_TOKEN` 환경변수 (없으면 즉시 에러 종료 — public만 조회되는데 조용히 0건으로 보이는 상황 방지)
- 회사 하나 실패는 전체를 막지 않고 `errors`에 담아 계속 진행

## data/companies.json 스키마
```json
{"companies": [{"type": "org", "org": "naver-hyperclovax", "display_name": "네이버 (하이퍼클로바X)"}]}
```
회사 추가/삭제는 이 파일을 직접 편집하면 된다 (사람이 읽고 고치기 쉽도록 plain JSON 유지).
