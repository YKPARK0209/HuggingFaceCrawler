---
name: hf-excel
description: 정제된 마스터 데이터셋(data/master_dataset.jsonl)으로 엑셀(.xlsx) 보고서를 생성한다. 전체 모델 목록 시트 + 이번 실행 변경분 시트를 만든다. "엑셀 만들어줘", "이번 주 변경사항 시트로 뽑아줘" 요청에 사용.
---

# hf-excel

## 역할
`data/master_dataset.jsonl` 전체를 "All Models" 시트(회사→다운로드수 내림차순)로, `logs/last_run_changes.json`을 "This Run Changes" 시트로 만들어 `output/huggingface_models.xlsx`를 생성한다. 100% 결정론적 — AI 개입 없음.

## 스크립트 계약 (`scripts/build_excel.py` — 아직 미구현)
```
python scripts/build_excel.py \
  --master-file data/master_dataset.jsonl \
  --changes-file logs/last_run_changes.json \
  --output output/huggingface_models.xlsx
# stdout: {"rows":N,"changed_rows":N,"output":"output/huggingface_models.xlsx"}
```
`pandas.ExcelWriter(engine="openpyxl")`로 작성 후 `openpyxl`로 컬럼 너비 자동 조정.

## 컬럼 구성
hf-refine에서 확정한 마스터 스키마를 그대로 따른다 — 이 스킬은 별도의 컬럼 선택/변환을 하지 않는다 (아직 마스터 스키마 자체가 TBD이므로, 확정되면 이 문서에 실제 컬럼 목록을 추가한다).

## 에러 처리
- `master_dataset.jsonl`이 비어있거나 없으면 **빈 엑셀을 만들지 말고 에러로 중단**한다 — 크롤링/정제가 한 번도 성공한 적 없다는 신호이므로, 조용히 빈 엑셀을 만들면 "정상적으로 0건"으로 오인된다.
- `last_run_changes.json`이 없으면 "This Run Changes" 시트만 비워두고 계속 진행.
