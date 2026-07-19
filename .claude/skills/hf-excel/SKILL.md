---
name: hf-excel
description: 정제된 마스터 데이터셋(data/master_dataset.jsonl)에서 제외 판정(excluded)되지 않은 모델만 골라 엑셀(.xlsx) 보고서를 생성한다. 전체 모델 목록 시트 + 이번 실행 변경분 시트를 만든다. "엑셀 만들어줘", "이번 주 변경사항 시트로 뽑아줘" 요청에 사용.
---

# hf-excel

## 역할
`data/master_dataset.jsonl`에서 **`excluded: true`가 아닌 레코드만** "All Models" 시트로, `logs/last_run_changes.json` 중 제외되지 않은 것만 "This Run Changes" 시트로 만들어 `output/huggingface_models.xlsx`를 생성한다. 100% 결정론적 — AI 개입 없음.

## 컬럼 순서 (hf-refine에서 확정한 25개 필드, 이 순서 그대로)
**모델 ID**(재크롤링/업데이트 매칭 키 — 원본 HF repo id 그대로), 모델명, 회사명, URL, **기술 리포트 링크**(arxiv/PDF/README 링크 중 감지된 것, 클릭 시 바로 열림), 모델설명, 특화 도메인, 지원 모달리티, 지원 언어, 라이선스, 공개일, 최근 업데이트일, 규모(파라미터), 컨텍스트 길이, 정밀도, 모델 아키텍처, 모델 구축 방식, 베이스 모델, 벤치마크_언어지식이해, 벤치마크_전문논리능력, 벤치마크_멀티모달이해, 벤치마크_안전성신뢰성, 벤치마크_한국어, 벤치마크_기타, 지식 최신성(일자)

## null → "미기재" (빈 칸 아님)
마스터 데이터셋의 `null` 값은 엑셀에서 문자열 **"미기재"**로 채운다 (빈 칸으로 남기지 않음). 단, 정렬(회사명/최근 업데이트일)은 `null`인 상태로 먼저 수행하고, **정렬이 끝난 뒤에** "미기재"로 채운다 — 먼저 채우면 문자열이 날짜/숫자 정렬에 섞여 순서가 깨진다.

## 정렬
"All Models" 시트는 회사명 오름차순 → 그 안에서 최근 업데이트일 내림차순(최신 모델이 위로).

## 스크립트 계약 (`scripts/build_excel.py` — 구현 완료)
```
python scripts/build_excel.py \
  --master-file data/master_dataset.jsonl \
  --changes-file logs/last_run_changes.json \
  --output output/huggingface_models.xlsx
# 실제 파일명에는 오늘 날짜가 자동으로 붙는다: output/huggingface_models_2026-07-19.xlsx
# stdout: {"rows":N,"excluded":N,"changed_rows":N,"output":"output/huggingface_models_2026-07-19.xlsx"}
```
`pandas.ExcelWriter(engine="openpyxl")`로 작성 후 `openpyxl`로 컬럼 너비 자동 조정. `master_dataset.jsonl`을 읽을 때 `excluded==true`인 행은 DataFrame 구성 전에 걸러낸다. `--output`에 넘긴 파일명의 stem에 `_YYYY-MM-DD`를 붙여 실제로 저장한다 (매주 실행 결과가 서로 덮어써지지 않고 회차별로 남는다).

## 에러 처리
- `master_dataset.jsonl`이 비어있거나 없으면 **빈 엑셀을 만들지 말고 에러로 중단**한다 — 크롤링/정제가 한 번도 성공한 적 없다는 신호이므로, 조용히 빈 엑셀을 만들면 "정상적으로 0건"으로 오인된다.
- 전부 `excluded: true`라서 표시할 행이 0개인 경우도 같은 이유로 에러 취급(원인을 stdout에 남기고 중단).
- `last_run_changes.json`이 없으면 "This Run Changes" 시트만 비워두고 계속 진행.

## 참고
"제외된 모델이 몇 개, 왜 제외됐는지"의 공식 이력은 이 스킬이 아니라 `hf-pipeline`이 전체 파이프라인 완료 시 `logs/pipeline_history.jsonl`에 남긴다 (`hf-pipeline` 스킬 참조). 이 스킬은 그 판정을 읽어서 필터링만 할 뿐, 로그를 쓰지 않는다.
