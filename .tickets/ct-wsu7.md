---
id: ct-wsu7
status: closed
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

**2026-11-02T17:49:45Z**

2026-11-02 impl-model: fixes 2-5 on r1b-model (rebased on 44785aee): d4657856 url_state_lines, ee0c973b document_identities (only multi-member components sorted; dedup-first measured worse), 628772c9 capture_sources (the evidence export narrows; raw columns rejoin via capture_evidence), 1499dae7 link pipeline. All 17 release files are byte-identical before and after (v21 frozen inputs plus the spicy-regs pin, 34 GiB, 2 threads). Materialized 41.8 to 38.1 GB; peak RSS 15.75 to 12.61 GiB. 16 GiB with 2 threads still fails at appearance_records_resolved (a 789.5 MB sort reservation), so it waits on fix 1, which comes after r1b-f. The 53.4 GB spill is profile_completeness capture_dup (GROUP BY a text receipt_key; binary key spills 208 MB); sent upstream to engine-spill, no SQL workaround. Full lane requested before merge.

**2026-11-02T19:00:59Z**

2026-11-02 owner decision: the release's model run uses a backported engine (5dae611 plus the ss-vuwa fix, a backport of DataFusion #21633: the spill writer passed Arrow IPC slices that rewrote every referenced view buffer on each 8192-row slice, quadratic). Measured on the repro: 383.4 MB and 0.9 s, values matching a direct scan; 5dae611 fails at 16-19 s. The DataFusion 55.2 / Arrow 59 / Iceberg main upgrade (owner redirect) lands after the release. D2-D4 stay on 5dae611 (producer versions hash code, not the engine); the full model waits for the re-pin. Disk floor for the model run is 15 GiB.

**2026-11-02T19:20:11Z**

2026-11-02 release engine b0342a7368fa1e2c7e957f228c12f74cd1117f65 (docspec-rs release/5dae611-spill, tag docspec-5dae611-spill): 5dae611 + CI-only commits + vendored datafusion-physical-plan 53.1.0 + the ss-vuwa spill compaction backport. Lead verified independently: the stripped darwin-arm64 binary's sha256 is fed9ea73dd8d141a6257288e961bf51331409ad581380510b8af726745fd48cd (168,825,592 bytes; nm shows only undefined externals); the vendored crate at 159ee78 is byte-identical to crates.io datafusion-physical-plan-53.1.0 (diff -r, only .cargo-ok differs); the fix diff is spill/mod.rs, spill_manager.rs, in_progress_spill_file.rs, sorts/sort.rs and src/budget.rs. Repro: 383.4 MB spill in 0.8 s, values matching a direct scan. docspec-rs CI against release-train ddbf676f: run 41506139189. Linux build pending. D2-D4 keep the 5dae611 config; the model run gets its own config after the re-pin.

**2026-11-02T20:21:07Z**

2026-11-02 the full model run on release-train f7413130 (engine b0342a7, 16 GiB pool, 2 threads) passed every compute step, with peak RSS 9.40 GiB, and stopped at the release key invariant: 44 unexplained blank filenames (v21 inputs at an older head gave 1,487), 9 invalid URL keys, 1 generic title. inv-rca is reading all 54 rows against raw sources, fixing each cause at its layer (branch r1b-inv), and naming the re-run each fix needs. Earlier: 08c1afb0 (recording tracks ranked once) is byte-identical on all 17 files and fixed the recordings_entity sort failure. D2 34.75 min, peak 2.10 GiB, 67,540 html readings (1,416,679 total); D3 about 14.5 min, 1,341,215 filename rows (+30,140); D4 602 s, peak 8.54 GiB, meeting_records 24,431, appearance_records 66,490.

**2026-11-02T22:05:26Z**

2026-11-02 lead: linux-amd64 b0342a7 (sha256 9e5cc34f…, 196,665,824 bytes) uploaded create-only to congressional-tech-runtime at runtime/docspec/b0342a7…/linux-amd64/9e5cc34f…/docspec by the checked-in publish-docspec-runtime.py, with exact readback, using 15-minute temporary credentials scoped to that key prefix. Descriptor: .cache/runtime-b0342a7/runtime-artifact.json (the uploaded descriptor matches it). The DOCSPEC_RUNTIME_ARTIFACT variable switches to it at the main merge.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
