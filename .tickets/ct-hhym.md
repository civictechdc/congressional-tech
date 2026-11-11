---
id: ct-hhym
status: closed
deps: []
links: []
created: 2026-11-11T20:10:40Z
type: bug
priority: 2
assignee: mikewolfd
---
# Hosted shard 6 runs at the 30-minute limit: shard by measured duration, not file round-robin

dev.py shard_files (scripts/dev.py:480) deals sorted files round-robin, so shards balance by file count. Hosted run 43089201388 (2026-11-11, beadd0b3): shards 1-5 took 9-19 min, shard 6 was cancelled by validate-explorer.yml's timeout-minutes: 30 at 91% (still passing); its earlier runs took 24-26 min (42938206878, 43084507486), so ordinary runner variance cancels it and fails 'validate'. Fix at the root: assign files to shards by recorded duration (e.g. pytest --durations output or a checked-in per-file timing file refreshed by CI, greedy longest-first), keeping the deterministic, disjoint, full-coverage property crc-xk7r established; raising the timeout only hides the drift.


## Notes

**2026-11-11T23:05:43Z**

Fixed on claude/dx-shard-durations: failing tests 52fcc094, greedy LPT implementation + .github/scripts/test-shard-durations.json + refresh-shard-durations CLI 09212bc6, blind review follow-up tests 61eae8b8 and JUnit custody hardening 318f7a09 (greybeard PASS, etl-workflow PASS, evolutionary-refactoring PASS). Root cause confirmed from hosted JUnit artifacts (43084507486 + 43089201388): adding test_member_appearances.py in 78933231 shifted round-robin indices so shard 6 stacked test_archive_selective.py (908.0s), test_phase2_model_entities.py (316.3s) and test_daily_producer_records.py (237.7s) for 1,740.0s (29.00m) of pytest execution vs 473.2s (7.89m) on shard 5. Under greedy LPT across all 531 production-offline files, every shard 1/6..6/6 balances to 924.2s-924.3s (15.40m-15.41m; -46.9% max shard load). Full stacked 6-shard lane run (.cache/archive-release/lanes-dx-stack-r91j-hhym-fc874b7c, 22:49:02Z to 23:04:55Z): shards 1-6 finished in 595.7s to 701.8s each (9m55s to 11m41s, 13,020 passed, all exit 0) and storage-loopback exit 0 (35 passed in 30.7s).

