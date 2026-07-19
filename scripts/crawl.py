#!/usr/bin/env python3
"""Crawl Hugging Face Hub for companies in data/companies.json, fetching full
model metadata + README for models that are new or changed since the last run.

Contract (see .claude/skills/hf-crawl/SKILL.md):
  stdout: single JSON line {"new":N,"updated":N,"unchanged":N,"removed":N,"errors":[...]}
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from huggingface_hub import HfApi

load_dotenv()


def jsonable(obj):
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [jsonable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__dict__"):
        return jsonable(vars(obj))
    return obj


def sanitize(model_id):
    return model_id.replace("/", "__")


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def fetch_readme(model_id, token):
    url = f"https://huggingface.co/{model_id}/raw/main/README.md"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urlopen(Request(url, headers=headers), timeout=20) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None


def crawl_org(org, api, token, state_dir, raw_dir, now, totals, errors):
    state_path = state_dir / f"{org}.json"
    state = load_json(state_path, {"org": org, "last_crawled_at": None, "models": {}})

    try:
        listing = list(api.list_models(author=org))
    except Exception as e:
        errors.append(f"{org}: {e}")
        return

    seen_ids = set()
    org_raw_dir = raw_dir / org

    for m in listing:
        model_id = m.id
        seen_ids.add(model_id)
        sha = m.sha
        prev = state["models"].get(model_id)

        if prev is None or prev.get("status") == "removed":
            kind = "new"
        elif prev.get("sha") != sha:
            kind = "updated"
        else:
            kind = "unchanged"

        if kind in ("new", "updated"):
            try:
                info = api.model_info(model_id)
                readme = fetch_readme(model_id, token)
            except Exception as e:
                errors.append(f"{model_id}: {e}")
                continue
            org_raw_dir.mkdir(parents=True, exist_ok=True)
            dump = {"info": jsonable(vars(info)), "readme": readme}
            (org_raw_dir / f"{sanitize(model_id)}.json").write_text(
                json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        totals[kind] += 1
        first_seen_at = prev.get("first_seen_at", now) if prev else now
        state["models"][model_id] = {
            "sha": sha,
            "last_modified": jsonable(m.last_modified),
            "status": "active",
            "first_seen_at": first_seen_at,
            "last_seen_at": now,
            "removed_at": None,
        }

    for model_id, rec in state["models"].items():
        if rec["status"] == "active" and model_id not in seen_ids:
            rec["status"] = "removed"
            rec["removed_at"] = now
            totals["removed"] += 1

    state["last_crawled_at"] = now
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--companies-file", required=True)
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--log-file", required=True)
    ap.add_argument("--org", default=None, help="크롤링할 org 하나만 지정 (디버깅용)")
    args = ap.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        print(json.dumps({"error": "HF_TOKEN not set"}))
        sys.exit(1)

    state_dir = Path(args.state_dir)
    raw_dir = Path(args.raw_dir)
    log_path = Path(args.log_file)
    state_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    companies = json.loads(Path(args.companies_file).read_text(encoding="utf-8"))["companies"]
    if args.org:
        companies = [c for c in companies if c["org"] == args.org]
        if not companies:
            print(json.dumps({"error": f"unknown org: {args.org}"}))
            sys.exit(1)

    api = HfApi(token=token)
    now = datetime.now(timezone.utc).isoformat()
    totals = {"new": 0, "updated": 0, "unchanged": 0, "removed": 0}
    errors = []

    for company in companies:
        crawl_org(company["org"], api, token, state_dir, raw_dir, now, totals, errors)

    log_entry = {"timestamp": now, **totals, "errors": errors}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    print(json.dumps({**totals, "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
