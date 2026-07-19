#!/usr/bin/env python3
"""Download a model's technical report (PDF) and split it into named sections so the
hf-report enrichment step only has to read the ONE section it actually needs (e.g.
"Evaluation" for missing benchmarks, "Method"/"Training" for construction method) --
never the whole paper. This script spends zero LLM tokens; it is pure text extraction.

Contract (see .claude/skills/hf-report/SKILL.md):
  stdout: {"model_id":...,"sections_found":[...],"cache_path":"...","cached":bool}
       or {"model_id":...,"error":"..."} (exit 1)
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

MIN_EXTRACTED_LEN = 200  # below this, assume a scanned/image PDF we can't handle here

SECTION_HEADING_RE = re.compile(
    r'^\s*(?:\d+\.?\s+)?'
    r'(Abstract|Introduction|Related Work|Method|Methodology|Model(?:\s+Architecture)?|'
    r'Architecture|Training|Pretraining|Post-?training|Experiments?|Evaluations?|Results|'
    r'Benchmarks?|Discussion|Limitations|Conclusion|References)\s*$',
    re.IGNORECASE | re.MULTILINE,
)


def arxiv_abs_to_pdf_url(url):
    if "arxiv.org/abs/" in url:
        return url.replace("/abs/", "/pdf/")
    return url


def download_pdf(url, dest):
    req = Request(arxiv_abs_to_pdf_url(url), headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as resp:
        dest.write_bytes(resp.read())


def extract_text(pdf_path):
    import pdfplumber
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def split_sections(full_text):
    matches = list(SECTION_HEADING_RE.finditer(full_text))
    sections = {}
    for i, m in enumerate(matches):
        name = m.group(1).strip().title()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        content = full_text[start:end].strip()
        if not content:
            continue
        sections[name] = (sections[name] + "\n\n" + content) if name in sections else content
    return sections


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", required=True)
    ap.add_argument("--report-url", required=True)
    ap.add_argument("--cache-dir", required=True)
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_name = args.model_id.replace("/", "__")
    pdf_path = cache_dir / f"{safe_name}.pdf"
    sections_path = cache_dir / f"{safe_name}_sections.json"

    if sections_path.exists():
        print(json.dumps({"model_id": args.model_id, "cache_path": str(sections_path), "cached": True},
                          ensure_ascii=False))
        return

    try:
        download_pdf(args.report_url, pdf_path)
        full_text = extract_text(pdf_path)
    except Exception as e:
        print(json.dumps({"model_id": args.model_id, "error": f"download/extract failed: {e}"},
                          ensure_ascii=False))
        sys.exit(1)

    if len(full_text.strip()) < MIN_EXTRACTED_LEN:
        print(json.dumps({"model_id": args.model_id,
                           "error": "extracted text too short (likely a scanned/image PDF, not handled)"},
                          ensure_ascii=False))
        sys.exit(1)

    sections = split_sections(full_text)
    sections_path.write_text(json.dumps(sections, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "model_id": args.model_id,
        "sections_found": list(sections.keys()),
        "cache_path": str(sections_path),
        "cached": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
