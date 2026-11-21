#!/usr/bin/env python3
"""Split the V6.5 gap-fill gold (shards 32..37) into a training part and a held-out test part.

Stratified by (shard group, labeled kind or status). Each stratum draws from its own RNG seeded by the stratum
name, so adding a shard later never moves a doc that was already assigned. A stratum of 1 doc trains; 2 or 3
docs hold out 1; 4 or more hold out round(30%).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random

from .paths import resolve_docmeta_v65_dir

ROOT = resolve_docmeta_v65_dir()
OUT_DIR = ROOT / "lookups_and_gold"
GROUPS = {32: "rare", 33: "rare", 34: "rare", 35: "rare", 36: "unseen_cluster", 37: "lineage"}
TEST_FRAC = 0.30


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--v65-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    v65_dir = args.v65_dir.expanduser().resolve() if args.v65_dir is not None else resolve_docmeta_v65_dir()
    out_dir = v65_dir / "lookups_and_gold"
    strata: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for shard, group in GROUPS.items():
        path = v65_dir / "outputs_2000" / f"gold_shard_{shard}.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            gold = json.loads(rec["messages"][-1]["content"])
            status = str(gold.get("status") or "usable")
            kind = str(gold.get("primary_kind") or "other") if status == "usable" else f"status:{status}"
            strata[f"{group}|{kind}"].append((str(rec["link_key_hex"]).lower(), line))
    train: list[str] = []
    test: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    for name in sorted(strata):
        rows = sorted(strata[name])
        rng = random.Random(int(hashlib.sha256(f"v65-split|{name}".encode()).hexdigest()[:16], 16))
        rng.shuffle(rows)
        n_test = 0 if len(rows) < 2 else (1 if len(rows) < 4 else max(1, round(len(rows) * TEST_FRAC)))
        test += [line for _, line in rows[:n_test]]
        train += [line for _, line in rows[n_test:]]
        counts[name] = {"train": len(rows) - n_test, "test": n_test}
    out_dir.mkdir(exist_ok=True)
    (out_dir / "train_v6_5_gapfill_train.jsonl").write_text("\n".join(train) + "\n", encoding="utf-8")
    (out_dir / "eval_v6_5_gapfill_test.jsonl").write_text("\n".join(test) + "\n", encoding="utf-8")
    (out_dir / "eval_v6_5_gapfill_all.jsonl").write_text("\n".join(train + test) + "\n", encoding="utf-8")
    by_group = Counter()
    for name, c in counts.items():
        by_group[name.split("|")[0] + ":train"] += c["train"]
        by_group[name.split("|")[0] + ":test"] += c["test"]
    manifest = {"train": len(train), "test": len(test), "by_group": dict(sorted(by_group.items())), "strata": counts}
    (out_dir / "split_v6_5_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("train", "test", "by_group")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
