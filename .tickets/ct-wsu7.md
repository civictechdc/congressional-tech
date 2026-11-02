---
id: ct-wsu7
status: open
deps: []
links: [ct-deg8, ct-r8jd]
created: 2026-11-02T16:35:07Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [model, memory, etl, phase2]
---
# Model working set: build on candidates, group before distinct, project narrow columns

etl-model 2026-11-02 (.cache/archive-release/investigations/model/): the release model config (16 GiB pool, 2 threads) fails on 5a3121c at appearance_records_resolved (789.5 MB reservation); 34 GiB passes (peak RSS 17.5 GiB). 590 MB of input decodes 9.5x (captures 661 B/row, 15x); steps materialize 41.8 GB (three full-width captures copies 9.6 GB; evidence exports 1.39 GB vs 77 MB public; link fan-out 6.3M rows, 8.3 GB); captures scanned 49 times in 23 readers. Heavy steps: appearance_records_resolved 10.5 GB (6 copies of a 1.33 GB hash table on captures, not the 66K candidates), url_state_lines 7.8 GB (per-group count DISTINCT), document_identities 4.16 GB (ordered DISTINCT array_agg), link_targets 2.57 GB. An engine aggregate spilled 53.4 GB for 4.15M rows under EXPLAIN ANALYZE (trigger not isolated; ss-oxg1).

## Acceptance Criteria

Fixes 1-5 land with byte-identical release files on v21 frozen inputs (every sha256 equal before and after); per-step peak and materialized bytes measured before and after; the release config (16 GiB, 2 threads) passes the full model; only the model profile digest moves.


## Notes

**2026-11-02T17:17:02Z**

Owner decision 2026-11-02: run the full model only after the witness-step fix lands on meetings, at the release's own settings (16 GiB, 2 threads); no 4-thread stop-gap or larger pool.
