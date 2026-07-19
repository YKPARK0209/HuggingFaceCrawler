#!/usr/bin/env python3
"""1st-pass (deterministic) refinement of raw HF crawl data into the master dataset.

Contract (see .claude/skills/hf-refine/SKILL.md):
  stdout: {"upserted":N,"pending_ai":N,"excluded_readme_too_short":N}
  writes: data/master_dataset.jsonl, logs/last_run_changes.json, logs/pending_ai_inputs.json
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

README_MIN_LEN = 200
PENDING_AI_PATH = Path("logs/pending_ai_inputs.json")

LANGUAGE_MAP = {"en": "영어", "ko": "한국어", "ja": "일본어", "zh": "중국어"}
LICENSE_MAP = {
    "apache-2.0": "Apache-2.0",
    "mit": "MIT",
    "cc-by-4.0": "CC-BY-4.0",
    "cc-by-nc-4.0": "CC-BY-NC-4.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "openrail": "OpenRAIL",
    "openrail++": "OpenRAIL",
}
MODALITY_ORDER = ["Text", "Image", "Video", "3D", "Audio"]
PIPELINE_TAG_MODALITIES = {
    "image-text-to-text": {"Text", "Image"},
    "visual-question-answering": {"Text", "Image"},
    "document-question-answering": {"Text", "Image"},
    "image-to-text": {"Text", "Image"},
    "text-to-image": {"Text", "Image"},
    "image-classification": {"Image"},
    "object-detection": {"Image"},
    "image-segmentation": {"Image"},
    "image-to-image": {"Image"},
    "unconditional-image-generation": {"Image"},
    "zero-shot-image-classification": {"Image"},
    "depth-estimation": {"Image"},
    "video-classification": {"Video"},
    "text-to-video": {"Text", "Video"},
    "video-to-video": {"Video"},
    "image-to-3d": {"Image", "3D"},
    "text-to-3d": {"Text", "3D"},
    "unconditional-3d-generation": {"3D"},
    "automatic-speech-recognition": {"Text", "Audio"},
    "text-to-speech": {"Text", "Audio"},
    "audio-classification": {"Audio"},
    "audio-to-audio": {"Audio"},
    "voice-activity-detection": {"Audio"},
    "any-to-any": {"Text", "Image", "Audio"},
}

BENCHMARK_FIELDS = [
    "benchmark_language_knowledge", "benchmark_technical", "benchmark_multimodal",
    "benchmark_safety", "benchmark_korean", "benchmark_other",
]
REC_2ND_STAGE_FIELDS = [
    "description", "domain", "construction_method", "context_length", "knowledge_cutoff",
] + BENCHMARK_FIELDS
NEEDS_CANDIDATES = [
    "description", "domain", "modality", "language", "license", "parameters",
    "context_length", "precision", "construction_method", "base_model", "knowledge_cutoff",
] + BENCHMARK_FIELDS


BENCHMARK_HEADING_RE = re.compile(
    r'^#+\s*.*(benchmark|evaluations?|eval\s*results?).*$', re.IGNORECASE | re.MULTILINE
)
HEADING_RE = re.compile(r'^#+\s', re.MULTILINE)
IMAGE_RE = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
TABLE_ROW_RE = re.compile(r'^\s*\|.*\|.*\|\s*$', re.MULTILINE)


def find_image_only_benchmark_urls(body):
    """Detect every 'Benchmark/Evaluation'-ish section that contains image(s) but no
    markdown table (i.e. the only place numbers could be is inside the image).
    Returns the combined list of image URLs across all such sections, else []."""
    urls = []
    for m in BENCHMARK_HEADING_RE.finditer(body):
        section_start = m.end()
        next_heading = HEADING_RE.search(body, section_start)
        section_end = next_heading.start() if next_heading else len(body)
        section = body[section_start:section_end]
        if TABLE_ROW_RE.search(section):
            continue
        urls.extend(IMAGE_RE.findall(section))
    return urls


def strip_frontmatter(readme):
    if not readme:
        return ""
    text = readme
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    return text.strip()


def format_languages(langs):
    if not langs:
        return None
    if isinstance(langs, str):
        langs = [langs]
    if len(langs) >= 3:
        return f"다국어({len(langs)}개 언어)"
    names = []
    for code in langs:
        name = LANGUAGE_MAP.get(str(code).lower())
        if name and name not in names:
            names.append(name)
    if names:
        order = ["한국어", "영어", "일본어", "중국어"]
        names.sort(key=lambda n: order.index(n) if n in order else 99)
        return ", ".join(names)
    return f"기타({','.join(str(c) for c in langs)})"


def format_license(card_license, license_name):
    if not card_license:
        return None
    key = str(card_license).lower()
    if key in LICENSE_MAP:
        return LICENSE_MAP[key]
    if key == "other":
        return f"기타({license_name})" if license_name else "기타"
    return card_license


def extract_parameters(info):
    st = info.get("safetensors")
    if st and st.get("total"):
        return int(st["total"])
    model_name = info["id"].split("/", 1)[-1]
    m = re.search(r'(\d+(?:\.\d+)?)\s*[Bb](?:[^a-zA-Z]|$)', model_name)
    if m:
        return int(round(float(m.group(1)) * 1_000_000_000))
    m = re.search(r'(\d+(?:\.\d+)?)\s*[Mm](?:[^a-zA-Z]|$)', model_name)
    if m:
        return int(round(float(m.group(1)) * 1_000_000))
    return None


def extract_precision(info):
    st = info.get("safetensors")
    if st and st.get("parameters"):
        norm = []
        for k in st["parameters"].keys():
            k = k.upper()
            k = {"F16": "FP16", "F32": "FP32"}.get(k, k)
            norm.append(k)
        return "+".join(sorted(set(norm)))
    return None


def classify_modality(pipeline_tag):
    if not pipeline_tag:
        return None
    tag = pipeline_tag.lower()
    modalities = PIPELINE_TAG_MODALITIES.get(tag, {"Text"})
    return ", ".join(m for m in MODALITY_ORDER if m in modalities)


def extract_architecture(info):
    # architectures[0] (the actual transformers class name, e.g. "LlamaForCausalLM") is used
    # alone -- config.model_type is free text the model author fills in and is NOT standardized,
    # so prefixing it produced misleading labels (e.g. naver-hyperclovax used "vlm" for one
    # release and "hyperclovax_vlm" for another release of a very similar architecture).
    config = info.get("config") or {}
    architectures = config.get("architectures") or []
    if architectures:
        return architectures[0]
    model_type = config.get("model_type")
    if model_type:
        return model_type.capitalize()
    return None


REPORT_LINK_RE = re.compile(
    r'\[[^\]]*(?:technical report|tech report|paper)[^\]]*\]\(([^)\s]+)\)', re.IGNORECASE
)


def find_technical_report_url(model_id, info, body):
    """Detect a technical report/paper linked to this model, in priority order:
    1) an arxiv: tag (HF auto-adds this when the README links an arXiv paper) -> arxiv.org/abs/<id>
    2) a .pdf file uploaded directly to the repo (siblings) -> direct HF resolve link
    3) a "Technical Report"/"Paper" markdown link inside the README body (may be an external URL,
       or a relative path to a repo file -- normalized to a full HF resolve link either way)
    Returns None if no such reference exists (genuinely undocumented, not a guess)."""
    for tag in info.get("tags") or []:
        if tag.startswith("arxiv:"):
            return f"https://arxiv.org/abs/{tag.split(':', 1)[1]}"

    for sib in info.get("siblings") or []:
        name = sib.get("rfilename", "")
        if name.lower().endswith(".pdf"):
            return f"https://huggingface.co/{model_id}/resolve/main/{name}"

    m = REPORT_LINK_RE.search(body or "")
    if m:
        url = m.group(1)
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"https://huggingface.co/{model_id}/resolve/main/{url.lstrip('./')}"

    return None


def load_master(path):
    master = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                master[rec["model_id"]] = rec
    return master


def save_master(master, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for model_id in sorted(master.keys()):
            f.write(json.dumps(master[model_id], ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--companies-file", required=True)
    ap.add_argument("--master-file", required=True)
    ap.add_argument("--changes-out", required=True)
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    companies = json.loads(Path(args.companies_file).read_text(encoding="utf-8"))["companies"]
    org_to_display = {c["org"]: c["display_name"] for c in companies}

    master_path = Path(args.master_file)
    master = load_master(master_path)

    now = datetime.now(timezone.utc).isoformat()
    changes = []
    pending = []
    upserted = 0
    excluded_short = 0

    if raw_dir.exists():
        for org_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
            org = org_dir.name
            display_name = org_to_display.get(org, org)

            for raw_file in sorted(org_dir.glob("*.json")):
                dump = json.loads(raw_file.read_text(encoding="utf-8"))
                info = dump["info"]
                readme = dump.get("readme")
                model_id = info["id"]

                existing = master.get(model_id)
                change_type = "updated" if existing is not None else "new"
                first_seen_at = existing.get("first_seen_at", now) if existing else now

                body = strip_frontmatter(readme)
                card = info.get("card_data") or {}

                rec = {
                    "model_id": model_id,
                    "model_name": model_id.split("/", 1)[-1],
                    "org": org,
                    "company_name": display_name,
                    "url": f"https://huggingface.co/{model_id}",
                    "release_date": (info.get("created_at") or "")[:10] or None,
                    "last_modified_date": (info.get("last_modified") or "")[:10] or None,
                    "architecture": extract_architecture(info),
                    "modality": classify_modality(info.get("pipeline_tag")),
                    "precision": extract_precision(info),
                    "parameters": extract_parameters(info),
                    "sha": info.get("sha"),
                    "first_seen_at": first_seen_at,
                    "last_refined_at": now,
                }
                rec["technical_report_url"] = find_technical_report_url(model_id, info, body)
                rec["language"] = format_languages(card.get("language"))
                rec["license"] = format_license(card.get("license"), card.get("license_name"))
                base_model = card.get("base_model")
                if isinstance(base_model, list):
                    base_model = ", ".join(base_model) if base_model else None
                rec["base_model"] = base_model

                for f in REC_2ND_STAGE_FIELDS:
                    rec[f] = None
                rec["benchmark_image_urls"] = find_image_only_benchmark_urls(body)

                if len(body) < README_MIN_LEN:
                    rec["excluded"] = True
                    rec["exclusion_reason"] = "readme_too_short"
                    excluded_short += 1
                else:
                    rec["excluded"] = False
                    rec["exclusion_reason"] = None
                    needs = [f for f in NEEDS_CANDIDATES if rec.get(f) is None]
                    if "modality" not in needs:
                        # 1차의 pipeline_tag 매핑은 커스텀 VLM/옴니모델에서 "text-generation"처럼
                        # 뭉뚱그려진 값만 보고 잘못 판단하는 경우가 실제로 있었음(예: Omni-8B, Think-32B,
                        # Vision-Instruct-3B가 전부 1차에서는 "Text"로만 분류됨). 그래서 1차가 값을 채웠어도
                        # modality만은 항상 needs에 넣어 2차가 README 본문(Input/Output Format 등)을 보고
                        # 재확인/덮어쓰기하도록 강제한다.
                        needs.append("modality")
                    if needs:
                        already_filled = {
                            k: rec[k] for k in
                            ["license", "parameters", "precision", "language", "modality", "base_model", "architecture"]
                            if rec.get(k) is not None
                        }
                        pending.append({
                            "model_id": model_id,
                            "readme_body": body,
                            "already_filled": already_filled,
                            "needs": needs,
                        })

                master[model_id] = rec
                changes.append({"model_id": model_id, "change_type": change_type})
                upserted += 1

    save_master(master, master_path)

    changes_path = Path(args.changes_out)
    changes_path.parent.mkdir(parents=True, exist_ok=True)
    changes_path.write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8")

    PENDING_AI_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_AI_PATH.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "upserted": upserted, "pending_ai": len(pending), "excluded_readme_too_short": excluded_short,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
