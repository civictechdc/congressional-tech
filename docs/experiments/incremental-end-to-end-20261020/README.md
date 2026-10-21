# Integrated fixed-change measurement

This local generated-fixture experiment follows the maintained raw, catalog and viewer publication owners through one append and one state correction. Read `protocol.md` before running. The final comparison uses 4 versus 40 unrelated documents; earlier failed attempts remain in the evidence directory.

Run with the project Python environment:

```sh
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python docs/experiments/incremental-end-to-end-20261020/measure.py --output /absolute/new/local/evidence/directory
```

`--unrelated 4` or `--unrelated 40` runs one fresh case. Existing fixture transports retain native tables in memory and publish to a local conditional client. No provider, source acquisition, production write, or actual native engine is involved. Measurements distinguish logical Arrow/store boundaries from physical throughput.

The original baseline at dd2d4ac9 preserved exact selected values, IDs, old pins and publication hashes. Its 105 append-catalog read calls consumed 6,359 versus 49,595 Arrow rows; 84 calls reread two shared observation leaves. Bounded partition occupancy also increased rewritten rows and viewer payload bytes. This experiment does not establish constant whole-path cost or close ct-2ukk.

Full protocol, failures, per-run receipts, selected snapshots, hashes and summary: `/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/end-to-end/`.
