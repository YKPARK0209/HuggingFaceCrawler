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

**요구사항과의 매핑**: "이미 한 번 엑셀로 만든 모델은 제외하고, 새로 업로드된 것만 대상으로 하되, 기존에 기록한 것도 최종 업데이트일자가 달라졌으면 다시 기록한다"는 요구사항이 정확히 이 표와 같다 — `sha`가 안 바뀌면(=`lastModified`도 안 바뀜, 이 둘은 항상 같이 바뀜) unchanged로 완전히 스킵, `sha`가 바뀌면(=`lastModified`도 바뀜) updated로 재처리. `sha`를 실제 비교 기준으로 쓰는 이유는 날짜 문자열 비교보다 정확해서일 뿐, 의미는 "최종 업데이트일자가 달라졌는가"와 동일하다. 새로 추가한 회사는 `state/<org>.json` 자체가 없으므로 그 회사의 모든 모델이 자동으로 new가 된다 — 별도 처리 불필요.

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

## 스크립트 계약 (`scripts/crawl.py` — 구현 완료, tunib/naver-hyperclovax/upstage로 검증됨)
```
python scripts/crawl.py \
  --companies-file data/companies.json \
  --state-dir state/ \
  --raw-dir raw/ \
  --log-file logs/crawl_log.jsonl \
  [--org <slug>]
```
- 출력: `raw/<org>/<model_id_sanitized>.json` (슬래시는 `__`로 치환), `state/<org>.json` 갱신, `logs/crawl_log.jsonl`에 한 줄 append
- stdout 마지막 줄(다른 무엇도 출력하지 말 것 — 오케스트레이터가 이 한 줄만 읽는다): `{"new":N,"updated":N,"unchanged":N,"removed":N,"errors":["org: message", ...]}`
- 인증: `HF_TOKEN` 환경변수 (없으면 즉시 에러 종료 — public만 조회되는데 조용히 0건으로 보이는 상황 방지)
- 회사 하나 실패는 전체를 막지 않고 `errors`에 담아 계속 진행

**`logs/crawl_log.jsonl`은 crawl.py를 실행할 때마다(수동 디버깅 포함) 매번 append되는 기술 로그다.** 이건 "최종 리포트를 발송했다"는 공식 이력이 아니다 — 그 공식 이력(`logs/pipeline_history.jsonl`)은 `hf-pipeline`이 크롤→정제→엑셀→이메일 전체를 성공적으로 끝냈을 때만 별도로 남긴다 (`hf-pipeline` 스킬 참조). 특정 회사만 테스트로 재크롤링하거나 샘플을 확인하는 용도로 이 스크립트를 실행해도 `pipeline_history.jsonl`에는 아무 흔적도 남지 않는다.

## data/companies.json 스키마
```json
{"companies": [{"type": "org", "org": "naver-hyperclovax", "display_name": "네이버 (하이퍼클로바X)"}]}
```
회사 추가/삭제는 이 파일을 직접 편집하면 된다 (사람이 읽고 고치기 쉽도록 plain JSON 유지).
