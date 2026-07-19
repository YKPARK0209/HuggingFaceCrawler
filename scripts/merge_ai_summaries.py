#!/usr/bin/env python3
"""Merge the AI-produced 2nd-stage fields into the master dataset, then apply the
final inclusion/exclusion decision.

Contract (see .claude/skills/hf-refine/SKILL.md):
  stdout: {"merged":N,"excluded_this_run":N,"pending_remaining":N|null}
  writes: data/master_dataset.jsonl (updated), logs/last_run_excluded.json
  optional: --pending-file trims merged model_ids out of that queue file (used for
  the 2nd-stage AI backlog; omitted entirely when reusing this script for the
  report-enrichment merge, which has no pending queue).
  no-op-safe if --ai-outputs is missing or empty.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_FIELDS = ["parameters", "description", "license"]


def load_master(path):
    master = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            master[rec["model_id"]] = rec
    return master


def save_master(master, path):
    with path.open("w", encoding="utf-8") as f:
        for model_id in sorted(master.keys()):
            f.write(json.dumps(master[model_id], ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai-outputs", required=True)
    ap.add_argument("--master-file", required=True)
    ap.add_argument("--changes-file", required=True)
    ap.add_argument("--excluded-out", required=True)
    ap.add_argument("--pending-file", default=None,
                     help="If given, remove merged model_ids from this AI-backlog queue "
                          "(checkpoints progress so a partial batch is never lost).")
    args = ap.parse_args()

    master_path = Path(args.master_file)
    master = load_master(master_path)
    now = datetime.now(timezone.utc).isoformat()

    merged = 0
    merged_ids = set()
    ai_path = Path(args.ai_outputs)
    if ai_path.exists():
        content = ai_path.read_text(encoding="utf-8").strip()
        if content:
            ai_outputs = json.loads(content)
            for entry in ai_outputs:
                model_id = entry.get("model_id")
                rec = master.get(model_id)
                if rec is None:
                    continue
                for k, v in entry.items():
                    if k == "model_id":
                        continue
                    rec[k] = v
                rec["last_refined_at"] = now
                merged += 1
                merged_ids.add(model_id)

    changes_path = Path(args.changes_file)
    touched_ids = set()
    if changes_path.exists():
        changes = json.loads(changes_path.read_text(encoding="utf-8"))
        touched_ids = {c["model_id"] for c in changes}

    excluded_this_run = []
    for model_id, rec in master.items():
        if rec.get("exclusion_reason") == "readme_too_short":
            if model_id in touched_ids:
                excluded_this_run.append({"model_id": model_id, "exclusion_reason": "readme_too_short"})
            continue
        missing = [f for f in REQUIRED_FIELDS if not rec.get(f)]
        rec["excluded"] = bool(missing)
        rec["exclusion_reason"] = ("missing: " + ", ".join(missing)) if missing else None
        if missing and model_id in touched_ids:
            excluded_this_run.append({"model_id": model_id, "exclusion_reason": rec["exclusion_reason"]})

    save_master(master, master_path)

    excluded_path = Path(args.excluded_out)
    excluded_path.parent.mkdir(parents=True, exist_ok=True)
    excluded_path.write_text(json.dumps(excluded_this_run, ensure_ascii=False, indent=2), encoding="utf-8")

    pending_remaining = None
    if args.pending_file:
        pending_path = Path(args.pending_file)
        if pending_path.exists():
            content = pending_path.read_text(encoding="utf-8").strip()
            pending = json.loads(content) if content else []
            pending = [p for p in pending if p.get("model_id") not in merged_ids]
            pending_path.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
            pending_remaining = len(pending)

    print(json.dumps({
        "merged": merged, "excluded_this_run": len(excluded_this_run), "pending_remaining": pending_remaining,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
