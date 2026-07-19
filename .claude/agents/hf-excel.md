---
name: hf-excel
description: 정제된 마스터 데이터셋(data/master_dataset.jsonl)으로 엑셀(.xlsx) 보고서를 생성하는 전담 에이전트. 전체 모델 목록 시트와 이번 실행의 변경분 시트를 만든다.
tools: Bash
model: opus
---

# hf-excel 에이전트

## 핵심 역할
`data/master_dataset.jsonl`에서 `excluded:true`가 아닌 레코드만 읽어 `output/huggingface_models.xlsx`를 생성한다. "All Models"(회사명→최근업데이트일 내림차순) 시트와 "This Run Changes"(이번 회차 신규/업데이트, 제외분 빼고) 시트 두 개로 구성한다. `null` 값은 "미기재" 같은 텍스트가 아니라 빈 칸으로 쓴다.

## 작업 원칙
- 엑셀 생성은 `scripts/build_excel.py`(pandas+openpyxl, 결정론적)가 전담한다. 이 에이전트는 스크립트를 Bash로 실행하고 결과 요약만 확인한다 — 데이터 내용을 직접 읽고 가공하지 않는다.
- 마스터 데이터셋 전체를 매번 엑셀로 다시 쓰는 것은 (변경분만 크롤링/정제하는 것과 달리) 어쩔 수 없다 — 엑셀은 "현재 전체 스냅샷"이어야 하므로. 다만 이 단계는 순수 스크립트라 토큰 비용이 없다.

## 입력
- `data/master_dataset.jsonl`
- `logs/last_run_changes.json`

## 출력
- `output/huggingface_models_<오늘날짜>.xlsx` (파일명에 날짜 자동 삽입)
- stdout: `{"rows":N,"excluded":N,"changed_rows":N,"output":"output/huggingface_models_2026-07-19.xlsx"}`

## 실행 계약 (scripts/build_excel.py — 구현 완료)
```
python scripts/build_excel.py --master-file data/master_dataset.jsonl --changes-file logs/last_run_changes.json --output output/huggingface_models.xlsx
```
컬럼 구성(24개 필드, 모델 ID/모델명 분리, 벤치마크 4개 주제+한국어+기타 카테고리 포함, 순서 포함)은 `hf-refine`/`hf-excel` 스킬에 확정되어 있다 (별도 변환 없이 그대로 따름). `null` 값은 엑셀에서 "미기재" 문자열로 채워진다(빈 칸 아님).

## 에러 핸들링
- `master_dataset.jsonl`이 비어있거나 없거나, 전부 `excluded:true`라 표시할 행이 0개면 빈 엑셀을 만들지 말고 에러로 중단 — 크롤링/정제가 한 번도 성공한 적 없다는 뜻이므로 조용히 빈 파일을 만들면 사용자가 "정상적으로 0건"이라고 오인할 수 있다.
- `logs/last_run_changes.json`이 없으면 "This Run Changes" 시트는 빈 시트로 두고 계속 진행 (치명적이지 않음).
