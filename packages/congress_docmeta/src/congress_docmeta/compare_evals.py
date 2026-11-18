#!/usr/bin/env python3
"""Side-by-side metrics for `eval_docmeta_blind.py` reports: `compare_docmeta_evals.py a.json b.json ...`."""

from __future__ import annotations

import json
from pathlib import Path
import sys

KEYS = (
    "n", "headline_mean", "primary_kind_acc", "status_acc", "chamber_acc", "congress_acc", "committees_f1",
    "subcommittees_f1", "dates_f1", "event_type_acc", "personas_name_f1", "personas_name_role_f1",
    "personas_name_etype_f1", "correspondence_flow_acc", "short_titles_f1", "refs_f1", "topics_f1",
    "work_addr_gold", "work_addr_pred", "work_addr_matched", "work_addr_recall", "work_addr_precision",
    "work_addr_agreement", "work_addr_pred_gold_blank",
    "strict_valid_pct", "avg_out_tok", "truncated_docs", "anomaly_flagged",
)


def main(paths: list[str]) -> int:
    reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    for set_name in reports[0]["sets"]:
        print(f"\n== {set_name} ==")
        print(f"{'metric':26s}" + "".join(f"{r['label'][:18]:>20s}" for r in reports))
        for k in KEYS:
            vals = [r["sets"].get(set_name, {}).get("metrics", {}).get(k) for r in reports]
            if any(v is not None for v in vals):
                print(f"{k:26s}" + "".join(f"{'' if v is None else v:>20}" for v in vals))
        sweeps = [r["sets"].get(set_name, {}).get("sweep") for r in reports]
        if any(sweeps):
            print(f"{'sweep docs_per_sec':26s}" + "".join(f"{(s or {}).get('docs_per_sec', ''):>20}" for s in sweeps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
