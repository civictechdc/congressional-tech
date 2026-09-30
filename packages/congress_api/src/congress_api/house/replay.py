"""Enrich retained House state from an unchanged local research observation.

Run ``python -m congress_api.house.replay --state house.json.gz --cache CACHE
--output OUTPUT/house.json.gz``. This makes no requests. A cache is usable only
when reparsing reproduces all previously retained data and its XML update date.
Changed or incomplete observations require a live refresh instead. Cache file
digests and replay time are recorded separately from acquisition/check times.

Compatibility and source-specific protection rules:
/docs/congress-api-contracts.md#replay-protection-matrix
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from congress_api.house.evidence import SCHEMA_VERSION
from congress_api.house.records import parsed, timestamp
from congress_api.house.repository import cached_xml
from congress_api.inventory.common import read_state, write_state

MATCH_FIELDS = ("documents", "witnesses", "amendments", "xml_update", "status", "witness_status")


def replay(state, cache):
    report = {"mode": "offline", "replayed_at": timestamp(), "events": {}}
    output = dict(state)
    for event, saved in sorted(state.items()):
        schema = saved.get("evidence", {}).get("schema_version")
        if schema == SCHEMA_VERSION:
            report["events"][event] = {"status": "current"}
            continue
        if schema not in (None, "1.0"):
            report["events"][event] = {"status": "skipped", "reason": "unknown evidence schema"}
            continue
        meeting = cache / "docs_house_xml/meeting" / f"{event}.xml"
        witness = cache / "docs_house_xml/wlist" / f"{event}.xml"
        html = cache / "docs_house" / f"{event}.html"
        root, wlist = cached_xml(meeting), cached_xml(witness)
        if root is None and not html.exists():
            report["events"][event] = {"status": "skipped", "reason": "no usable raw observation"}
            continue
        page = html.read_text(errors="replace") if html.exists() else ""
        wstatus = "present" if wlist is not None else "absent" if witness.with_suffix(".none").exists() else "unfetched"
        candidate = parsed(root, wlist, page, wstatus)
        differences = [field for field in MATCH_FIELDS if saved.get(field) != candidate[field]]
        if differences:
            report["events"][event] = {"status": "skipped", "reason": "cache does not reproduce saved observation", "fields": differences}
            continue
        paths = ([meeting] if root is not None else []) + ([witness] if wlist is not None else [])
        if root is None or wstatus == "unfetched":
            paths += [html] if html.exists() else []
        if wstatus == "absent":
            paths.append(witness.with_suffix(".none"))
        inputs = [{"path": path.relative_to(cache).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                  for path in paths]
        receipt = {"mode": "offline", "replayed_at": report["replayed_at"], "matched_fields": list(MATCH_FIELDS), "inputs": inputs}
        # Never rewrite checked/version/retrieved_at or any earlier live receipt.
        output[event] = {**saved, "evidence": candidate["evidence"], "replay": receipt}
        report["events"][event] = {"status": "replayed", "inputs": inputs}
    report["counts"] = dict(Counter(row["status"] for row in report["events"].values()))
    return output, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.state.resolve() == args.output.resolve():
        parser.error("--output must differ from --state; keep the input snapshot for comparison")
    state, report = replay(read_state(args.state), args.cache)
    write_state(args.output, state)
    report_path = args.output.parent / "house-replay.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "report": str(report_path), **report["counts"]}))


if __name__ == "__main__":
    main()
