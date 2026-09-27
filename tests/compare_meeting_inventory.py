"""Compare all ten production tables against the frozen a1705b6 research outputs."""
import argparse
import collections
import csv
import hashlib
import io
import json
import subprocess
from pathlib import Path

KEYS = {
    "hearing_text_sources": ["event_id"], "meetings_without_records": ["event_id"], "meeting_completeness": ["event_id"],
    "meeting_witnesses": ["event_id", "name"], "house_documents_found": ["event_id", "url"],
    "house_witnesses_found": ["event_id", "name", "panel"], "house_amendments_found": ["event_id", "kind", "url"],
    "senate_hearing_pages_found": ["event_id"], "senate_witnesses_found": ["event_id", "name"], "senate_documents_found": ["event_id", "url"],
}


def compare(output):
    result = {}
    for name, fields in KEYS.items():
        baseline = subprocess.check_output(["git", "show", f"a1705b6:docs/youtube-coverage/research/data/{name}.csv"])
        actual = (output / f"{name}.csv").read_bytes()
        left, right = [list(csv.DictReader(io.StringIO(data.decode()))) for data in (baseline, actual)]
        def group(rows):
            out = collections.defaultdict(list)
            for r in rows:
                out[tuple(r[f] for f in fields)].append(r)
            return out
        before, after = group(left), group(right)
        changes, counts = [], collections.Counter()
        for key in sorted(before.keys() & after.keys()):
            assert len(before[key]) == len(after[key]), f"{name}: unexplained duplicate count at {key}"
            for old, new in zip(before[key], after[key]):
                assert old.keys() == new.keys(), f"{name}: columns changed"
                difference = {c: [old[c], new[c]] for c in old if old[c] != new[c]}
                if difference:
                    changes.append({"key": key, "values": difference})
                    counts.update(difference.keys())
        result[name] = {"rows": [len(left), len(right)], "keys": [len(before), len(after)],
                        "removed_keys": sorted(before.keys() - after.keys()), "added_keys": sorted(after.keys() - before.keys()),
                        "changed_columns": dict(counts), "changes": changes, "byte_identical": baseline == actual,
                        "sha256": hashlib.sha256(actual).hexdigest()}
        print(name, result[name]["rows"], "changed columns", dict(counts), "byte-identical", baseline == actual)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    a.report.write_text(json.dumps(compare(a.output_dir), indent=2) + "\n")
