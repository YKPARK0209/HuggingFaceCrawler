---
name: hf-pipeline
description: HuggingFaceCrawler 전체 파이프라인(크롤링→1차정제→2차AI정제→엑셀생성→이메일발송→git커밋/푸시)을 순서대로 실행하는 오케스트레이터. "허깅페이스 크롤링 실행해줘", "이번 주 모델 업데이트 확인", "파이프라인 돌려줘", "크롤링 다시 실행", "hf-pipeline 재실행", "이전 결과 기준으로 다시 돌려줘" 등 이 프로젝트의 전체 흐름을 실행/재실행/부분재실행하라는 요청이면 항상 이 스킬을 사용한다. Claude Code 예약 실행(주 1회)이 호출하는 대상이기도 하다.
---

# hf-pipeline 오케스트레이터

## 실행 모드: 단일 에이전트 순차 실행 (팀/서브에이전트 스폰 없음)
이 파이프라인은 순서가 고정된 선형 흐름이라 실시간 조율이나 병렬성의 이득이 없고, 매주 자동 실행되므로 스폰 비용이 매번 누적되면 안 된다. **`hf-crawl`/`hf-refine`/`hf-excel`/`hf-email`/`hf-report` 에이전트 정의는 존재하지만, 이 자동 실행 경로에서는 스폰하지 않는다** — 이 스킬을 실행하는 에이전트 본인이 Bash로 각 스크립트를 직접 순서대로 돌리고, stdout 한 줄 요약만 확인한다. 그 에이전트 정의들은 사람이 한 단계만 따로 디버깅하고 싶을 때 `Agent` 도구로 개별 호출(`model: "opus"` 명시)하기 위한 문서다.

## Phase 0: 컨텍스트 확인 (항상 먼저)
- `state/`와 `data/master_dataset.jsonl`이 있으면 → 정기(증분) 실행. 없으면 → 최초 실행(자연히 전부 new로 처리됨). 둘 다 아래 "실행 순서"를 그대로 따르면 된다 — 별道 분기 코드 불필요.
- 사용자가 "크롤링은 됐고 메일만 다시" 처럼 부분 실행을 원하면, 해당 단계부터 시작하고 그 이전 단계의 최신 산출물(파일)을 그대로 입력으로 쓴다.
- 사용자가 "이 회사만 다시" 라고 하면 1단계(crawl)에 `--org <slug>`만 붙여서 실행하고, 이후 단계는 전체 마스터 데이터셋 기준으로 그대로 진행(다른 회사 데이터는 그대로 유지됨).
- **이 실행이 "Claude Code에 등록된 예약 스케줄"에 의해 자동 트리거된 것인지, 아니면 사람이 채팅으로 직접 요청한 수동/테스트 실행인지 먼저 구분한다.** 이건 9번(공식 이력 기록) 단계에서 로그를 남길지 말지를 결정하는 기준이다 — 아래 §logs/pipeline_history.jsonl 참조.

## 실행 순서
1. **crawl**: `python scripts/crawl.py --companies-file data/companies.json --state-dir state/ --raw-dir raw/ --log-file logs/crawl_log.jsonl [--org <slug>]` → stdout 한 줄 확보. (`crawl_log.jsonl`은 이 스크립트가 실행될 때마다 매번 쌓이는 기술 로그일 뿐, 공식 이력이 아니다 — 8번 참조.)
2. **refine 1차**: `python scripts/refine.py --raw-dir raw/ --companies-file data/companies.json --master-file data/master_dataset.jsonl --changes-out logs/last_run_changes.json` → stdout 한 줄 확보 (`{"upserted":N,"pending_ai":N,"excluded_readme_too_short":N}`). README 200자 미만인 모델은 여기서 바로 `excluded:true`로 처리되고 2차 대상에서 빠진다.
3. **refine 2차(AI)**: `logs/pending_ai_inputs.json` 확인. **비어있으면 이 단계 전체를 건너뛴다(파일도 열지 않는다).** 비어있지 않으면 `hf-refine` 스킬의 필드별 지침(1차/2차 담당, 통제 어휘, "미기재 대신 null", 벤치마크 분류)대로 처리해 `logs/ai_outputs.json`에 기록.
4. **merge**: `python scripts/merge_ai_summaries.py --ai-outputs logs/ai_outputs.json --master-file data/master_dataset.jsonl --changes-file logs/last_run_changes.json --excluded-out logs/last_run_excluded.json` (2차를 건너뛰었으면 no-op). 이 단계에서 **필수 3필드(규모/모델설명/라이선스) 중 하나라도 null이면 `excluded:true`** 처리 — `logs/last_run_excluded.json`에 이번 회차 신규 제외 목록 기록.
5. **이미지 벤치마크 재확인** (`hf-refine` 스킬 §3차 참조): `master_dataset.jsonl`에서 `excluded:false` + `benchmark_image_urls` 비어있지 않음 + 벤치마크_* 전부 null인 모델만 골라 이미지를 다운로드해 직접 보고, 값이 실제로 읽히면(예: 숫자 라벨 있는 막대그래프) 반영한다. 라벨 없는 차트라 읽을 수 없으면 그대로 null 유지. 이미 제외된 모델·텍스트로 벤치마크를 이미 확보한 모델은 손대지 않는다 — 최종 포함분에만 비용을 쓴다.
6. **기술 리포트 보강** (`hf-report` 스킬 참조): `excluded:false` + `technical_report_url` 존재 + (벤치마크_* 전부 null 이거나 `construction_method`가 null)인 모델만 골라, `python scripts/extract_report_sections.py --model-id <id> --report-url <url> --cache-dir raw/report_cache`로 리포트를 섹션 분해한 뒤 필요한 섹션(Evaluation/Method 등) 하나만 읽어 보강 → `logs/report_enrichment_outputs.json`에 기록. 그 뒤 `python scripts/merge_ai_summaries.py --ai-outputs logs/report_enrichment_outputs.json --master-file data/master_dataset.jsonl --changes-file logs/last_run_changes.json --excluded-out logs/last_run_excluded.json`로 다시 병합(같은 병합 스크립트 재사용 가능 — 임의 키를 덮어쓰는 범용 로직이라).
7. **excel**: `python scripts/build_excel.py --master-file data/master_dataset.jsonl --changes-file logs/last_run_changes.json --output output/huggingface_models.xlsx` → stdout 한 줄 확보 (`{"rows":N,"excluded":N,"changed_rows":N}`). `excluded:true` 행은 자동으로 빠진다.
8. **email**: `python scripts/send_email.py --excel-file output/huggingface_models.xlsx --recipients-file data/email_recipients.json --master-file data/master_dataset.jsonl --changes-file logs/last_run_changes.json --excluded-file logs/last_run_excluded.json --total-rows <7번 rows> --changed-rows <7번 changed_rows> --excluded-count <7번 excluded>` → stdout 한 줄 확보. 본문에 회사/모델/상태(신규·업데이트·미등재) 표가 HTML로 들어간다. 실패해도 9번은 진행.
9. **commit & push** (1~7이 성공했다면 — 이메일 성공 여부와 무관):
   ```
   git add -A -- state/ data/ logs/ output/
   git commit -m "HF crawl run <YYYY-MM-DD>: N new, M updated"
   git push
   ```
   `raw/`는 `.gitignore` 대상이라 add하지 않는다 (단 `raw/report_cache/`의 PDF/섹션 캐시도 `raw/` 하위라 자동으로 제외됨 — 매번 새로 받아도 되는 스크래치 데이터).
10. **공식 이력 기록** (아래 **두 조건을 모두** 만족할 때만 — §logs/pipeline_history.jsonl 참조): ① 이 실행이 **Claude Code 등록 예약 스케줄에 의해 자동 트리거**된 것이고, ② `send_email.py`가 `{"sent": true, ...}`를 반환해 **이메일이 실제로 전달 확인**됐을 때만, 지금까지 확보한 stdout 요약들 + `logs/last_run_excluded.json` 내용을 조합해 `logs/pipeline_history.jsonl`에 한 줄 append. **사람이 채팅으로 직접 요청한 실행(수동 재실행, 특정 회사만 테스트, 샘플 확인 등)은 크롤→정제→엑셀→이메일까지 전부 성공하더라도 이 로그에 절대 기록하지 않는다** — 이건 스케줄이 스스로 도는 "공식 회차"만을 위한 이력이다.
11. **최종 보고**: 1~10에서 이미 확보한 stdout 한 줄들만 조합해서 사람에게 보고한다. 파일을 다시 읽어 재확인하지 않는다.

## logs/pipeline_history.jsonl (공식 실행 이력 — "조회했다"는 이력을 남겨 나중에 다시 찾을 필요 없게 함)
**기록 조건(둘 다 필요): 예약 스케줄에 의한 자동 실행 + 이메일 발송 성공.** 사람이 대화로 직접 시킨 실행은 아무리 완벽하게 끝까지 성공해도 여기 남기지 않는다.
```json
{
  "timestamp": "2026-07-26T00:00:00Z",
  "new": 12, "updated": 5, "unchanged": 900, "removed": 1,
  "excel_rows": 850, "excel_excluded": 67, "excel_changed_rows": 17,
  "excluded_this_run": [{"model_id": "upstage/TinySolar-248m-4k", "exclusion_reason": "readme_too_short"}],
  "excel_path": "output/huggingface_models.xlsx",
  "email": {"sent": true, "recipients": 1, "subject": "..."},
  "crawl_errors": []
}
```
이 한 줄이면 "그 주에 뭐가 새로 나왔고, 뭘 왜 뺐고, 메일이 실제로 갔는지"를 나중에 파일을 다시 뒤지지 않고 바로 알 수 있다.

## 데이터 흐름
`companies.json` + `state/` → **crawl** → `raw/` → **refine 1차**(README 200자 미만 즉시 제외, `benchmark_image_urls` 탐지) → `master_dataset.jsonl` + `pending_ai_inputs.json` → **refine 2차(AI)** → `ai_outputs.json` → **merge**(필수 3필드 결측 제외 판정) → `master_dataset.jsonl`(갱신) + `last_run_excluded.json` → **이미지 벤치마크 재확인**(최종 포함분만) → `master_dataset.jsonl`(갱신) → **기술 리포트 보강**(여전히 공백 있는 최종 포함분만) → `master_dataset.jsonl`(갱신) → **excel**(제외 행 필터링) → `output/*.xlsx` → **email** → (부작용) → **git commit/push** → **pipeline_history.jsonl 기록**.

## 에러 핸들링
| 단계 | 실패 시 |
|---|---|
| crawl | 회사 단위 부분 실패는 계속 진행(실패 목록 보고). `HF_TOKEN` 자체가 없으면 전체 중단. |
| refine 1차 | raw 파일 하나 파싱 실패는 그 모델만 skip. |
| refine 2차(AI) | 실패해도 1차 결과만으로 계속 진행(AI 필드 null 유지). |
| excel | `master_dataset.jsonl`이 비어있거나, 전부 `excluded:true`라 표시할 행이 0개면 원인 모를 빈 성공으로 보이지 않도록 중단하고 보고. |
| email | 실패해도 **커밋은 그대로 진행** — 크롤링/정제/엑셀 결과는 이메일과 무관하게 보존되어야 함. 실패는 최종 보고에 눈에 띄게 표시. |
| commit/push | 실패 시 즉시 사람에게 보고 — 다음 실행이 자동으로 복구하지 않는다. |

## 테스트 시나리오
- **정상 흐름**: 신규/업데이트가 있는 상태로 1~11 전체 실행 → 엑셀 반영, 이메일 발송, git 커밋/푸시 확인.
- **에러 흐름**: 일부 회사의 HF API 호출이 실패하는 상황 → 나머지 회사는 정상 처리되고, 실패한 회사만 다음 실행으로 자연스럽게 이월(해당 회사 state가 갱신되지 않으므로)되는지 확인.

## 확정된 스키마
마스터 데이터셋/엑셀 25개 필드, 1차/2차 담당 구분, 통제 어휘, 제외(exclusion) 정책은 `hf-refine`/`hf-excel` 스킬에 확정되어 있다.

## 아직 미확정인 부분 (임의로 채우지 말 것)
- 변경 0건인 주에도 이메일을 보낼지 — 현재 기본값은 "보낸다"이며, 사용자가 원치 않으면 `hf-email` 스킬에 조건을 추가한다.
- README 200자 컷 임계값 — 등록된 회사 전체 크롤링 후 실제 분포를 보고 조정 가능한 잠정값이다.
