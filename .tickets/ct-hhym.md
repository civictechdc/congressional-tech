---
id: ct-hhym
status: open
deps: []
links: []
created: 2026-11-11T20:10:40Z
type: bug
priority: 2
assignee: mikewolfd
---
# Hosted shard 6 runs at the 30-minute limit: shard by measured duration, not file round-robin

dev.py shard_files (scripts/dev.py:480) deals sorted files round-robin, so shards balance by file count. Hosted run 43089201388 (2026-11-11, beadd0b3): shards 1-5 took 9-19 min, shard 6 was cancelled by validate-explorer.yml's timeout-minutes: 30 at 91% (still passing); its earlier runs took 24-26 min (42938206878, 43084507486), so ordinary runner variance cancels it and fails 'validate'. Fix at the root: assign files to shards by recorded duration (e.g. pytest --durations output or a checked-in per-file timing file refreshed by CI, greedy longest-first), keeping the deterministic, disjoint, full-coverage property crc-xk7r established; raising the timeout only hides the drift.

