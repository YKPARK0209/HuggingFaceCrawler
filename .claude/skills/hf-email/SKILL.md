---
name: hf-email
description: 완성된 엑셀 보고서(output/huggingface_models.xlsx)를 data/email_recipients.json에 등록된 수신자에게 Gmail SMTP로 첨부 발송한다. "메일 보내줘", "엑셀 발송해줘", "수신자 추가/삭제" 요청에 사용.
---

# hf-email

## 역할
Gmail SMTP(STARTTLS, smtp.gmail.com:587)로 `output/huggingface_models.xlsx`를 첨부해 수신자 전원에게 발송한다. 제목/본문은 고정 템플릿에 이번 회차 신규/업데이트 개수(`logs/run_log.jsonl` 최신 항목)만 채워 넣는다 — AI가 문구를 창작하지 않는다.

## 스크립트 계약 (`scripts/send_email.py` — 아직 미구현)
```
python scripts/send_email.py \
  --excel-file output/huggingface_models.xlsx \
  --recipients-file data/email_recipients.json \
  --run-log logs/run_log.jsonl
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
