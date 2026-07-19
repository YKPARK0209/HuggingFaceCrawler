#!/usr/bin/env python3
"""Send the finished Excel report to the configured recipients via Gmail SMTP,
with an HTML table in the body listing what was checked this run (new / updated /
excluded-for-missing-info) per company+model.

Contract (see .claude/skills/hf-email/SKILL.md):
  stdout: {"sent":true,"recipients":N,"subject":"..."} or {"sent":false,"error":"..."}
  env: GMAIL_ADDRESS, GMAIL_APP_PASSWORD
"""
import argparse
import json
import os
import smtplib
import sys
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

def load_master_lookup(path):
    lookup = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                lookup[rec["model_id"]] = rec
    return lookup


def load_json_list(path):
    p = Path(path)
    if p.exists() and p.read_text(encoding="utf-8").strip():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


def build_company_summaries(changes, excluded, master_lookup):
    """회사별로 이번 회차에 처리한 모델을 신규/업데이트/미등재 건수로 집계한다.
    모델을 하나하나 나열하면 회사 수가 늘어날수록 메일 본문이 한없이 길어지므로,
    상세 목록은 첨부 엑셀에 맡기고 메일 본문은 회사당 한 줄 요약만 보여준다."""
    excluded_ids = {e["model_id"] for e in excluded}
    counts = {}

    def bump(model_id, status):
        rec = master_lookup.get(model_id, {})
        company = rec.get("company_name", "-")
        c = counts.setdefault(company, {"new": 0, "updated": 0, "excluded": 0})
        c[status] += 1

    for c in changes:
        if c["model_id"] in excluded_ids:
            continue  # excluded takes precedence over new/updated in the count
        bump(c["model_id"], c["change_type"])
    for e in excluded:
        bump(e["model_id"], "excluded")

    summaries = []
    for company, c in counts.items():
        total = c["new"] + c["updated"] + c["excluded"]
        summaries.append({
            "company": company,
            "total": total,
            "new": c["new"],
            "updated": c["updated"],
            "excluded": c["excluded"],
        })
    summaries.sort(key=lambda r: r["company"])
    return summaries


def build_html_table(summaries):
    if not summaries:
        return "<p>이번 회차에 신규/업데이트/제외 항목이 없습니다.</p>"
    header = (
        "<tr>"
        "<th style='text-align:left;padding:4px 10px;border-bottom:2px solid #333;'>회사</th>"
        "<th style='text-align:left;padding:4px 10px;border-bottom:2px solid #333;'>처리 결과</th>"
        "</tr>"
    )
    body_rows = []
    for r in summaries:
        summary_text = (
            f"총 {r['total']}건 중 신규등재 {r['new']}건, "
            f"업데이트 {r['updated']}건, 정보부족으로 미등재 {r['excluded']}건"
        )
        body_rows.append(
            "<tr>"
            f"<td style='padding:4px 10px;border-bottom:1px solid #ddd;'>{escape(r['company'])}</td>"
            f"<td style='padding:4px 10px;border-bottom:1px solid #ddd;'>{escape(summary_text)}</td>"
            "</tr>"
        )
    return (
        "<table style='border-collapse:collapse;font-family:sans-serif;font-size:13px;'>"
        + header + "".join(body_rows) + "</table>"
    )


def build_html_body(total_rows, changed_rows, excluded_count, summaries):
    table_html = build_html_table(summaries)
    return f"""
    <html><body style="font-family:sans-serif;font-size:14px;">
    <p>Hugging Face 모델 크롤링 리포트입니다.</p>
    <ul>
      <li>전체 수록 모델: {total_rows}건</li>
      <li>이번 회차 신규/업데이트: {changed_rows}건</li>
      <li>정보 부족으로 제외된 모델: {excluded_count}건</li>
    </ul>
    <p>이번 회차에 확인한 회사별 처리 결과:</p>
    {table_html}
    <p style="margin-top:16px;">회사별 모델 상세 목록은 첨부된 엑셀 파일을 확인해주세요.</p>
    </body></html>
    """


def build_message(gmail_address, recipients, subject, html_body, excel_path):
    msg = MIMEMultipart()
    msg["From"] = gmail_address
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with excel_path.open("rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{excel_path.name}"')
    msg.attach(part)
    return msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel-file", required=True)
    ap.add_argument("--recipients-file", required=True)
    ap.add_argument("--master-file", required=True)
    ap.add_argument("--changes-file", required=True)
    ap.add_argument("--excluded-file", required=True)
    ap.add_argument("--total-rows", type=int, required=True)
    ap.add_argument("--changed-rows", type=int, required=True)
    ap.add_argument("--excluded-count", type=int, required=True)
    args = ap.parse_args()

    recipients = json.loads(Path(args.recipients_file).read_text(encoding="utf-8")).get("recipients", [])
    if not recipients:
        print(json.dumps({"sent": False, "error": "no recipients"}, ensure_ascii=False))
        return

    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not gmail_address or not gmail_password:
        print(json.dumps({"sent": False, "error": "GMAIL_ADDRESS/GMAIL_APP_PASSWORD not set"}, ensure_ascii=False))
        sys.exit(1)

    master_lookup = load_master_lookup(args.master_file)
    changes = load_json_list(args.changes_file)
    excluded = load_json_list(args.excluded_file)
    summaries = build_company_summaries(changes, excluded, master_lookup)

    subject = (f"[HF 모델 리포트] 신규/업데이트 {args.changed_rows}건 "
               f"(전체 {args.total_rows}건, 제외 {args.excluded_count}건)")
    html_body = build_html_body(args.total_rows, args.changed_rows, args.excluded_count, summaries)
    excel_path = Path(args.excel_file)

    last_error = None
    for _attempt in range(2):
        try:
            msg = build_message(gmail_address, recipients, subject, html_body, excel_path)
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(gmail_address, gmail_password)
                server.sendmail(gmail_address, recipients, msg.as_string())
            print(json.dumps({"sent": True, "recipients": len(recipients), "subject": subject}, ensure_ascii=False))
            return
        except Exception as e:
            last_error = str(e)

    print(json.dumps({"sent": False, "error": last_error}, ensure_ascii=False))
    sys.exit(1)


if __name__ == "__main__":
    main()
