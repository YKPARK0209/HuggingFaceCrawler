# HuggingFaceCrawler

Hugging Face Hub에서 등록된 회사(organization)들이 업로드하는 모델을 주기적으로 추적해, 이전 대비 신규/업데이트된 모델만 정제하고 엑셀로 만들어 이메일로 발송하는 파이프라인.

## 구조
- `data/companies.json` — 추적 대상 회사 목록 (편집 가능)
- `data/email_recipients.json` — 엑셀을 받을 이메일 수신자 목록 (편집 가능)
- `data/master_dataset.jsonl` — 정제된 전체 모델 데이터 (스크립트가 자동 관리)
- `state/<org>.json` — 회사별 마지막 크롤링 상태 (diff 판별용, 스크립트가 자동 관리)
- `logs/` — 실행 로그
- `output/huggingface_models.xlsx` — 최종 산출물
- `raw/` — 이번 실행 중에만 쓰는 스크래치 디렉토리 (git에 커밋 안 됨)
- `scripts/` — 크롤링/정제/엑셀/이메일 결정론적 파이썬 스크립트
- `.claude/agents/`, `.claude/skills/` — 이 프로젝트의 하네스 (Claude Code 에이전트/스킬 정의)

## 실행 방법
Claude Code에서 "허깅페이스 크롤링 실행해줘" 등으로 요청하면 `hf-pipeline` 스킬이 전체 파이프라인을 순서대로 실행한다 (크롤링 → 1차 정제 → 2차 AI 정제 → 엑셀 생성 → 이메일 발송 → git 커밋/푸시).

## 필요한 환경변수
- `HF_TOKEN` — Hugging Face read 토큰 (huggingface.co/settings/tokens)
- `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` — 이메일 발송용 Gmail 계정/앱 비밀번호

이 값들은 로컬에서는 `.env`(git에 커밋 안 됨)로, 예약 실행 시에는 schedule 설정의 시크릿으로 주입한다.

## 설치
```
pip install -r requirements.txt
```
