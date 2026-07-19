---
name: hf-pipeline
description: HuggingFaceCrawler 전체 파이프라인(크롤링→1차정제→2차AI정제→엑셀생성→이메일발송→git커밋/푸시)을 순서대로 실행하는 오케스트레이터. "허깅페이스 크롤링 실행해줘", "이번 주 모델 업데이트 확인", "파이프라인 돌려줘", "크롤링 다시 실행", "hf-pipeline 재실행", "이전 결과 기준으로 다시 돌려줘" 등 이 프로젝트의 전체 흐름을 실행/재실행/부분재실행하라는 요청이면 항상 이 스킬을 사용한다. Claude Code 예약 실행(주 1회)이 호출하는 대상이기도 하다.
---

# hf-pipeline 오케스트레이터

## 실행 모드: 단일 에이전트 순차 실행 (팀/서브에이전트 스폰 없음)
이 파이프라인은 순서가 고정된 선형 흐름이라 실시간 조율이나 병렬성의 이득이 없고, 매주 자동 실행되므로 스폰 비용이 매번 누적되면 안 된다. **`hf-crawl`/`hf-refine`/`hf-excel`/`hf-email` 에이전트 정의는 존재하지만, 이 자동 실행 경로에서는 스폰하지 않는다** — 이 스킬을 실행하는 에이전트 본인이 Bash로 각 스크립트를 직접 순서대로 돌리고, stdout 한 줄 요약만 확인한다. 그 에이전트 정의들은 사람이 한 단계만 따로 디버깅하고 싶을 때 `Agent` 도구로 개별 호출(`model: "opus"` 명시)하기 위한 문서다.

## Phase 0: 컨텍스트 확인 (항상 먼저)
- `state/`와 `data/master_dataset.jsonl`이 있으면 → 정기(증분) 실행. 없으면 → 최초 실행(자연히 전부 new로 처리됨). 둘 다 아래 "실행 순서"를 그대로 따르면 된다 — 별道 분기 코드 불필요.
- 사용자가 "크롤링은 됐고 메일만 다시" 처럼 부분 실행을 원하면, 해당 단계부터 시작하고 그 이전 단계의 최신 산출물(파일)을 그대로 입력으로 쓴다.
- 사용자가 "이 회사만 다시" 라고 하면 1단계(crawl)에 `--org <slug>`만 붙여서 실행하고, 이후 단계는 전체 마스터 데이터셋 기준으로 그대로 진행(다른 회사 데이터는 그대로 유지됨).

## 실행 순서
1. **crawl**: `python scripts/crawl.py --companies-file data/companies.json --state-dir state/ --raw-dir raw/ --log-file logs/run_log.jsonl [--org <slug>]` → stdout 한 줄 확보.
2. **refine 1차**: `python scripts/refine.py --raw-dir raw/ --companies-file data/companies.json --master-file data/master_dataset.jsonl --changes-out logs/last_run_changes.json` → stdout 한 줄 확보.
3. **refine 2차(AI)**: `logs/pending_ai_inputs.json` 확인. **비어있으면 이 단계 전체를 건너뛴다(파일도 열지 않는다).** 비어있지 않으면 `hf-refine` 스킬의 "2차 정제 작업 정의" 절 지시에 따라 처리 후 `logs/ai_outputs.json`에 기록.
4. **merge**: `python scripts/merge_ai_summaries.py --ai-outputs logs/ai_outputs.json --master-file data/master_dataset.jsonl` (2차를 건너뛰었으면 no-op).
5. **excel**: `python scripts/build_excel.py --master-file data/master_dataset.jsonl --changes-file logs/last_run_changes.json --output output/huggingface_models.xlsx` → stdout 한 줄 확보.
6. **email**: `python scripts/send_email.py --excel-file output/huggingface_models.xlsx --recipients-file data/email_recipients.json --run-log logs/run_log.jsonl` → stdout 한 줄 확보. 실패해도 7번은 진행.
7. **commit & push** (1~5가 성공했다면 — 이메일 성공 여부와 무관):
   ```
   git add -A -- state/ data/ logs/ output/
   git commit -m "HF crawl run <YYYY-MM-DD>: N new, M updated"
   git push
   ```
   `raw/`는 `.gitignore` 대상이라 add하지 않는다.
8. **최종 보고**: 1~7에서 이미 확보한 stdout 한 줄들만 조합해서 사람에게 보고한다. 파일을 다시 읽어 재확인하지 않는다.

## 데이터 흐름
`companies.json` + `state/` → **crawl** → `raw/` → **refine 1차** → `master_dataset.jsonl` + `pending_ai_inputs.json` → **refine 2차(AI)** → `ai_outputs.json` → **merge** → `master_dataset.jsonl`(갱신) → **excel** → `output/*.xlsx` → **email** → (부작용) → **git commit/push**.

## 에러 핸들링
| 단계 | 실패 시 |
|---|---|
| crawl | 회사 단위 부분 실패는 계속 진행(실패 목록 보고). `HF_TOKEN` 자체가 없으면 전체 중단. |
| refine 1차 | raw 파일 하나 파싱 실패는 그 모델만 skip. |
| refine 2차(AI) | 실패해도 1차 결과만으로 계속 진행(AI 필드 null 유지). |
| excel | `master_dataset.jsonl`이 비어있으면 원인 모를 빈 성공으로 보이지 않도록 중단하고 보고. |
| email | 실패해도 **커밋은 그대로 진행** — 크롤링/정제/엑셀 결과는 이메일과 무관하게 보존되어야 함. 실패는 최종 보고에 눈에 띄게 표시. |
| commit/push | 실패 시 즉시 사람에게 보고 — 다음 실행이 자동으로 복구하지 않는다. |

## 테스트 시나리오
- **정상 흐름**: 신규/업데이트가 있는 상태로 1~8 전체 실행 → 엑셀 반영, 이메일 발송, git 커밋/푸시 확인.
- **에러 흐름**: 일부 회사의 HF API 호출이 실패하는 상황 → 나머지 회사는 정상 처리되고, 실패한 회사만 다음 실행으로 자연스럽게 이월(해당 회사 state가 갱신되지 않으므로)되는지 확인.

## 아직 미확정인 부분 (임의로 채우지 말 것)
- 마스터 데이터셋/엑셀 최종 컬럼 구성 — 첫 실제 크롤링 데이터를 사용자와 함께 보고 확정 예정 (`hf-refine` 스킬 참조).
- 2차(AI) 정제가 정확히 무엇을 하는지 — 사용자가 별도로 지시할 예정.
- 변경 0건인 주에도 이메일을 보낼지 — 현재 기본값은 "보낸다"이며, 사용자가 원치 않으면 `hf-email` 스킬에 조건을 추가한다.
