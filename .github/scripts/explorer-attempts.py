#!/usr/bin/env python3
"""Retain completed collection-job conclusions without implying fresh observations."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


JOB_PROVIDERS = {
    "youtube": ("youtube",),
    "congress": ("congress.gov", "govinfo", "gpo-video-matches"),
    "meetings": ("docs.house.gov", "senate.committees", "meeting-inventory", "recovered-witnesses"),
    "committees": ("congress.gov:committees",),
}


def receipt(event, pages):
    run = event["workflow_run"]
    jobs = [job for page in pages for job in page["jobs"]]
    result = {}
    for name, providers in JOB_PROVIDERS.items():
        matching = [job for job in jobs if job["name"] == name]
        job = max(matching, key=lambda item: item.get("id", 0)) if matching else None
        result[name] = {
            "result": job.get("conclusion") or "unknown" if job else "unknown",
            "started_at": job.get("started_at") if job else None,
            "completed_at": job.get("completed_at") if job else None,
            "providers": list(providers),
        }
    return {
        "schema_version": "1.0",
        "run_id": run["id"], "run_attempt": run.get("run_attempt"), "head_sha": run["head_sha"],
        "run_url": run["html_url"], "conclusion": run.get("conclusion"),
        "completed_at": run.get("updated_at"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "jobs": result,
        "limitation": "Job conclusions describe acquisition attempts, not per-source fetch times. Failed or cancelled jobs may leave prior saved inputs in use; CSV and raw-state inputs can have different ages.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = receipt(json.loads(args.event.read_text()), json.loads(args.jobs.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n")


if __name__ == "__main__":
    main()
