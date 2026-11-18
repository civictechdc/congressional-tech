#!/usr/bin/env python3
"""Check pinned LibraryOfCongress/api.congress.gov ChangeLog.md and endpoint doc SHAs."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

DEFAULT_PIN = Path(__file__).resolve().parents[2] / "docs/data/congress-api-upstream/pin.json"
SHA1_HEX_RE = re.compile(r"^[0-9a-f]{40}$")


def validate_pin(pin: Any) -> dict[str, Any]:
    """Validate pin structure and required fields offline."""
    if not isinstance(pin, dict):
        raise ValueError("Pin must be a JSON object")
    repo = pin.get("repo")
    if not isinstance(repo, str) or "/" not in repo:
        raise ValueError("Pin requires repo as 'owner/name'")
    changelog = pin.get("changelog")
    if not isinstance(changelog, dict):
        raise ValueError("Pin requires changelog section")
    for field in ("path", "blob_sha", "latest_commit_sha", "latest_heading"):
        val = changelog.get(field)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"Pin changelog missing {field}")
    if not SHA1_HEX_RE.fullmatch(changelog["blob_sha"]):
        raise ValueError("Invalid changelog blob_sha")
    if not SHA1_HEX_RE.fullmatch(changelog["latest_commit_sha"]):
        raise ValueError("Invalid changelog latest_commit_sha")
    docs = pin.get("docs")
    if not isinstance(docs, dict) or not docs:
        raise ValueError("Pin requires docs map")
    for doc_path, meta in docs.items():
        if not isinstance(doc_path, str) or not isinstance(meta, dict) or not SHA1_HEX_RE.fullmatch(str(meta.get("blob_sha", ""))):
            raise ValueError(f"Invalid doc pin entry: {doc_path}")
    issues = pin.get("reviewed_issues")
    if not isinstance(issues, list) or not issues:
        raise ValueError("Pin requires reviewed_issues list")
    for idx, entry in enumerate(issues):
        if not isinstance(entry, dict):
            raise ValueError(f"Pin reviewed_issues[{idx}] must be an object")
        num = entry.get("number")
        if type(num) is not int or num <= 0:
            raise ValueError(f"Pin reviewed_issues[{idx}] requires positive int number")
    return pin


def extract_new_changelog_sections(markdown_text: str, known_heading: str) -> list[str]:
    """Return top-level '# ...' sections appearing before known_heading."""
    sections: list[str] = []
    current: list[str] = []
    for line in markdown_text.splitlines():
        if line.startswith("# "):
            if line.strip() == known_heading.strip():
                if current:
                    sections.append("\n".join(current))
                return sections
            if current:
                sections.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        sections.append("\n".join(current))
    return sections


def fetch_github_json(api_path: str) -> dict[str, Any]:
    """Read-only GitHub REST lookup via gh api."""
    out = subprocess.check_output(["gh", "api", api_path], text=True, timeout=30)
    return json.loads(out)


def check_live(pin: dict[str, Any], *, fetch=None) -> dict[str, Any]:
    """Compare pinned blob SHAs against live GitHub contents without mutating upstream."""
    if fetch is None:
        fetch = fetch_github_json
    repo = pin["repo"]
    drifted: list[dict[str, Any]] = []
    cl = pin["changelog"]
    cl_live = fetch(f"repos/{repo}/contents/{cl['path']}")
    new_sections: list[str] = []
    if cl_live.get("sha") != cl["blob_sha"]:
        raw = cl_live.get("content") or ""
        text = base64.b64decode(raw).decode("utf-8", "replace") if raw else ""
        new_sections = extract_new_changelog_sections(text, cl["latest_heading"])
        drifted.append({
            "path": cl["path"],
            "pinned_sha": cl["blob_sha"],
            "live_sha": cl_live.get("sha"),
            "new_sections": new_sections,
        })
    for doc_path, meta in pin["docs"].items():
        live_doc = fetch(f"repos/{repo}/contents/{doc_path}")
        if live_doc.get("sha") != meta["blob_sha"]:
            drifted.append({
                "path": doc_path,
                "pinned_sha": meta["blob_sha"],
                "live_sha": live_doc.get("sha"),
            })
    return {"repo": repo, "up_to_date": not drifted, "drifted": drifted}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=Path, default=DEFAULT_PIN)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Validate pin schema only (no network)")
    mode.add_argument("--live", action="store_true", help="Compare pin SHAs against live GitHub repository")
    args = parser.parse_args(argv)

    pin = validate_pin(json.loads(args.pin.read_text(encoding="utf-8")))
    if args.offline or not args.live:
        print(json.dumps({
            "repo": pin["repo"],
            "reviewed_at": pin.get("reviewed_at"),
            "changelog_sha": pin["changelog"]["blob_sha"],
            "reviewed_issues": [i["number"] for i in pin["reviewed_issues"]],
        }, indent=2))
        return 0

    status = check_live(pin)
    print(json.dumps(status, indent=2))
    return 0 if status["up_to_date"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
