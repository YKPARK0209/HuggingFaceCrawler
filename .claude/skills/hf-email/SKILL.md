---
name: hf-email
description: 완성된 엑셀 보고서(output/huggingface_models.xlsx)를 data/email_recipients.json에 등록된 수신자에게 Gmail SMTP로 첨부 발송한다. "메일 보내줘", "엑셀 발송해줘", "수신자 추가/삭제" 요청에 사용.
---

# hf-email

## 역할
Gmail SMTP(STARTTLS, smtp.gmail.com:587)로 `output/huggingface_models.xlsx`를 첨부해 수신자 전원에게 발송한다. 본문은 HTML이며 **이번 회차에 확인한 결과를 회사별 한 줄 요약 표로 보여준다** — 회사명 + "총 N건 중 신규등재 N건, 업데이트 N건, 정보부족으로 미등재 N건" 형태. 모델 단위 상세(모델명/비고 등)는 표에 나열하지 않는다 — 등록 회사가 계속 늘어날 것이므로 모델을 하나하나 다 적으면 본문이 한없이 길어진다. 상세는 첨부 엑셀에 맡기고 본문은 회사당 한 줄로 압축한다. 제목/본문 숫자는 고정 템플릿에 채워 넣을 뿐 — AI가 문구를 창작하지 않는다.

## 표 데이터 출처 (파일을 다시 파싱하지 않고, 이미 있는 3개 파일을 그대로 조합)
- `data/master_dataset.jsonl` — model_id → 회사명 조회용
- `logs/last_run_changes.json` — 이번 회차 신규/업데이트 목록
- `logs/last_run_excluded.json` — 이번 회차 신규 제외 목록(사유 포함)
같은 model_id가 changes와 excluded 둘 다에 있으면 **제외가 우선**(정보부족으로 미등재로 집계 — 신규/업데이트로 잡혔어도 결국 최종 엑셀엔 못 들어갔다는 뜻이므로). 회사별 집계는 `build_company_summaries()`가 담당한다.

## 스크립트 계약 (`scripts/send_email.py` — 구현 완료)
```
python scripts/send_email.py \
  --excel-file output/huggingface_models.xlsx \
  --recipients-file data/email_recipients.json \
  --master-file data/master_dataset.jsonl \
  --changes-file logs/last_run_changes.json \
  --excluded-file logs/last_run_excluded.json \
  --total-rows N --changed-rows N --excluded-count N
# stdout: {"sent":true,"recipients":1,"subject":"..."} 또는 {"sent":false,"error":"..."}
```
환경변수(반드시 환경변수로만 — 파일에 절대 하드코딩/커밋 금지): `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`.

## data/email_recipients.json
```json
{"recipients": ["owo2323@nipa.kr"]}
```
수신자 추가/삭제는 이 파일을 직접 편집.

## 에러 처리
- 발송 실패 시 스크립트 내부에서 1회 재시도. 그래도 실패하면 `{"sent":false,"error":"..."}`로 종료하되 **exit code는 0으로 유지하지 않는다** (오케스트레이터가 실패를 감지하되, 이미 커밋된 크롤링/정제/엑셀 결과는 되돌리지 않도록 오케스트레이터 쪽에서 판단).
- 수신자 목록이 비어있으면 발송을 스킵하고 `{"sent":false,"error":"no recipients"}`로 정상 종료 (치명적 에러 아님).
