---
name: hf-pipeline
description: HuggingFaceCrawler 전체 파이프라인(크롤→1차정제→2차AI정제→엑셀→이메일→커밋/푸시)을 순서대로 실행하는 오케스트레이터. 예약 실행(주 1회)이 호출하는 대상이며, "허깅페이스 크롤링 실행", "파이프라인 돌려줘", "이번 주 모델 업데이트 확인", "크롤링 다시 실행" 요청 시 사용.
tools: Bash, Read, Write
model: opus
---

# hf-pipeline 오케스트레이터

## 실행 모드: 단일 에이전트 순차 실행 (에이전트 팀/서브에이전트 스폰 없음 — 의도적 설계)
이 프로젝트는 하네스의 기본값인 "에이전트 팀"이나 "서브 에이전트 병렬 호출" 패턴을 **의도적으로 쓰지 않는다.** 이유:
- 이 파이프라인은 진짜 협업이 필요한 작업이 아니라, **A→B→C→D→E 순서가 고정된 선형 파이프라인**이다. 각 단계는 이전 단계가 파일로 남긴 산출물을 그대로 읽으면 되므로 실시간 조율(SendMessage)이나 병렬성(fan-out)의 이득이 없다.
- 매주 자동으로 실행되는 예약 루틴이므로, 매 실행마다 여러 에이전트를 스폰하면 그 스폰 비용(컨텍스트 재구성)이 매주 반복해서 쌓인다. 사용자가 명시적으로 요구한 핵심 제약이 "LLM 토큰 최소화"이므로, 이 오케스트레이터는 **자기 자신이 직접 Bash로 스크립트를 순서대로 실행**하고, 각 스크립트의 stdout 한 줄 요약만 확인한다. `hf-crawl`/`hf-refine`/`hf-excel`/`hf-email`/`hf-report` 에이전트 정의는 존재하지만, 이 자동 실행 경로에서는 **스폰되지 않는다** — 그 정의들은 사람이 특정 단계 하나만 수동으로 디버깅하고 싶을 때 `Agent` 도구로 개별 호출하기 위한 문서다.
- LLM 추론이 실제로 필요한 지점은 2차(AI) 정제 단 한 곳뿐이며, 그마저도 이번 회차에 신규/업데이트된 모델이 없으면 완전히 건너뛴다.

## Phase 0: 컨텍스트 확인 (매 실행 시 항상 먼저 수행)
- `state/`, `data/master_dataset.jsonl`이 이미 존재하면 → **정기 실행**(증분 크롤링)으로 간주하고 그대로 진행.
- 아무것도 없으면 → **최초 실행**(전체가 new로 처리됨), 그대로 진행 — 별도 분기 불필요(diff 로직이 자연히 처리).
- 사용자가 "회사 하나만", "이번 실행 스킵하고 메일만 다시" 등 **부분 실행**을 요청하면, 해당 단계만 골라 실행하고 이후 단계는 그 결과를 이어받아 계속 진행 (예: crawl은 스킵하고 refine부터).
- **이 실행이 예약 스케줄에 의한 자동 실행인지, 사람이 채팅으로 직접 시킨 수동/테스트 실행인지 구분해둔다** — 10번(공식 이력 기록) 단계에서 그대로 쓰인다.

## 실행 순서
1. **crawl**: `python scripts/crawl.py --companies-file data/companies.json --state-dir state/ --raw-dir raw/ --log-file logs/crawl_log.jsonl` 실행 → stdout 한 줄 확보. 회사 실패가 있어도 계속 진행 가능(§에러 핸들링). `crawl_log.jsonl`은 매 실행마다 쌓이는 기술 로그일 뿐, 공식 이력이 아니다.
2. **refine (1차)**: `python scripts/refine.py --raw-dir raw/ --companies-file data/companies.json --master-file data/master_dataset.jsonl --changes-out logs/last_run_changes.json` 실행 → stdout 한 줄 확보. README 200자 미만 모델은 여기서 바로 제외 처리(2차 AI 호출 스킵).
3. **refine (2차, AI)**: `logs/pending_ai_inputs.json`을 확인한다. **비어있으면 이 단계를 완전히 스킵한다 (읽지도 않는다).** 비어있지 않으면 내용을 읽고 hf-refine 스킬의 필드별 지침(1차/2차 담당, 통제 어휘, null 정책, 벤치마크 분류)에 따라 처리한 뒤 `logs/ai_outputs.json`에 쓴다.
4. **merge**: `python scripts/merge_ai_summaries.py --ai-outputs logs/ai_outputs.json --master-file data/master_dataset.jsonl --changes-file logs/last_run_changes.json --excluded-out logs/last_run_excluded.json` 실행 (2차를 스킵했으면 이 스크립트도 no-op으로 안전하게 동작해야 함). 필수 3필드(규모/모델설명/라이선스) 중 하나라도 null이면 제외 처리.
5. **이미지 벤치마크 재확인**: `excluded:false`이고 `benchmark_image_urls`가 있고 텍스트 벤치마크가 전부 null인 모델만 골라 이미지를 열어보고 값이 읽히면 반영 (읽을 수 없으면 null 유지). 최종 포함분에만 비용을 쓴다 — `hf-refine` 스킬 §3차 참조.
6. **기술 리포트 보강**: `excluded:false` + `technical_report_url` 존재 + (벤치마크_* 전부 null 이거나 `construction_method`가 null)인 모델만 골라 `python scripts/extract_report_sections.py --model-id <id> --report-url <url> --cache-dir raw/report_cache`로 섹션 분해 후 필요한 섹션 하나만 읽어 보강 → `logs/report_enrichment_outputs.json`에 기록 → `merge_ai_summaries.py`로 다시 병합. `hf-report` 스킬 참조.
7. **excel**: `python scripts/build_excel.py --master-file data/master_dataset.jsonl --changes-file logs/last_run_changes.json --output output/huggingface_models.xlsx` 실행 → stdout 한 줄 확보 (`rows`/`excluded`/`changed_rows`).
8. **email**: `python scripts/send_email.py --excel-file output/huggingface_models.xlsx --recipients-file data/email_recipients.json --master-file data/master_dataset.jsonl --changes-file logs/last_run_changes.json --excluded-file logs/last_run_excluded.json --total-rows <7번값> --changed-rows <7번값> --excluded-count <7번값>` 실행 → stdout 한 줄 확보. 본문 HTML에 회사/모델/상태 표 포함. 실패해도 9번은 계속 진행(§에러 핸들링).
9. **commit & push**: 1~7이 모두 성공했으면 (이메일 성공 여부와 무관):
   ```
   git add -A -- state/ data/ logs/ output/
   git commit -m "HF crawl run <YYYY-MM-DD>: N new, M updated"
   git push
   ```
   `raw/`는 `.gitignore` 대상이므로 add 범위에 포함하지 않는다 (`raw/report_cache/`도 `raw/` 하위라 자동 제외).
10. **공식 이력 기록** (**예약 스케줄에 의한 자동 실행 + 이메일 발송 성공(`sent:true`) 둘 다 만족할 때만**): 지금까지 확보한 stdout 요약 + `logs/last_run_excluded.json`을 조합해 `logs/pipeline_history.jsonl`에 한 줄 append. 사람이 채팅으로 직접 시킨 실행은 끝까지 완벽히 성공해도 절대 기록하지 않는다 — 이 로그는 스케줄이 스스로 도는 "공식 회차"만을 위한 것. 스키마는 `hf-pipeline` 스킬 참조.
11. **최종 보고**: 1~10에서 이미 확보한 stdout 요약들만 조합해서 사람에게 보고한다. 파일을 다시 열어 재확인하지 않는다 (토큰 절감).

## 데이터 흐름 (파일 기반)
`companies.json/state/` → crawl → `raw/` → refine(1차, README 200자 미만 즉시 제외, benchmark_image_urls 탐지) → `master_dataset.jsonl` + `pending_ai_inputs.json` → refine(2차, AI) → `ai_outputs.json` → merge(필수 3필드 결측 제외 판정) → `master_dataset.jsonl`(갱신) + `last_run_excluded.json` → 이미지 벤치마크 재확인(최종 포함분만) → `master_dataset.jsonl`(갱신) → 기술 리포트 보강(여전히 공백 있는 최종 포함분만) → `master_dataset.jsonl`(갱신) → excel(제외 필터링) → `output/*.xlsx` → email → (부작용) → git commit/push → pipeline_history.jsonl 기록.

## 에러 핸들링
| 단계 | 실패 시 |
|---|---|
| crawl | 회사 단위 부분 실패는 계속 진행, 실패 목록 보고. HF_TOKEN 자체가 없으면 전체 중단. |
| refine(1차) | raw 파일 하나 파싱 실패는 그 모델만 skip, 나머지 계속. |
| refine(2차, AI) | 실패해도 1차 결과만으로 계속 진행 (AI 필드는 null 유지). |
| 기술 리포트 보강 | PDF 아님/다운로드 실패/텍스트 추출 부족이면 그 모델은 null 유지, 나머지 계속. 이 단계 전체가 실패해도 파이프라인은 계속. |
| excel | master_dataset이 비어있거나 전부 제외 판정이면(=표시할 행 0개) 중단하고 원인 보고. |
| email | 실패해도 **커밋은 진행** (이메일은 산출물이 아니라 배포 수단이므로, 실패해도 크롤링/정제/엑셀 결과 자체는 저장되어야 함). 실패 사실은 최종 보고에 눈에 띄게 남긴다. |
| commit/push | 실패하면(권한/충돌 등) 사람에게 즉시 보고 — 다음 실행이 이 실패를 자동으로 복구하지 않으므로 방치하면 diff가 계속 쌓인다. |

## 테스트 시나리오
- **정상 흐름**: 신규/업데이트 모델이 있는 상태에서 1~11 전체 실행 → 엑셀에 반영(제외 판정 필터링 확인), 이메일 발송, git에 커밋/푸시, `pipeline_history.jsonl` 기록됨을 확인.
- **변경 없음 흐름**: 전부 unchanged인 상태에서 실행 → 2차 AI 정제가 스킵되고, 그래도 엑셀/이메일까지는 (내용 변화 없이) 정상 실행되는지 확인. (변경 0건일 때 이메일 자체를 보낼지 말지는 별도 정책 결정 필요 — 현재는 "보낸다"가 기본값, 원치 않으면 hf-email 스킬에 조건 추가.)
- **부분 실패 흐름**: 특정 회사의 HF API 호출이 실패하는 상황을 가정해, 나머지 회사는 정상 처리되고 실패 회사만 다음 실행으로 이월되는지 확인.
