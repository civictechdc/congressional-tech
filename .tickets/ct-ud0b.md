---
id: ct-ud0b
status: open
deps: []
links: [ct-4jms, ct-tk10]
created: 2026-11-02T13:59:14Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, gates, daily, phase2]
---
# Publish nightly when every change is a new row traced to new receipts

Owner decision 2026-11-02: after the fixed release, publish nightly without a person when every difference from the live release is an addition traceable to receipts newer than the live release, checked against the raw receipts (provenance), not by trusted change types. Any changed or removed existing value stops the publish and waits for a reviewed cause record (gate 1). Pulled forward from Round 4. Known limit: a bug that only adds wrong rows can still pass; the other gates (links, required fields, producer proof, end-to-end) still run.

## Acceptance Criteria

- Gate 1 records an automatic cause for an addition-only difference group only when every added row's source receipts post-date the live release's input record, verified by reading the receipt keys and dates, not the model.
- Any changed or removed existing value refuses as today.
- Tests: additions from new receipts pass; an added row from an old receipt refuses; a changed value refuses; a removed row refuses.
- The daily workflow (archive-jobs publish after capture) runs this unattended; the pointer flips only when all gates pass.


## Notes

**2026-11-02T15:55:47Z**

2026-11-02 impl-h r1b-h 1573be5c: implemented (3f122fc8): automatic_causes accepts a difference only when every new row is a new document whose body comes from a receipt outside the live release's set, dated after its newest, named by its raw receipt line; any changed or removed value, split, old or undated receipt, or untraceable row refuses. Four acceptance tests plus one through publish_candidate. Can't see: a bug that only adds wrong rows from new receipts. Still blocked on the daily path by gate 5 until daily production writes per-snapshot producer records (follow-up).

**2026-11-02T18:17:49Z**

2026-11-02 spec-run: the selective job's D2 stopped after 8 s with all 67,565 reads pending and no location (peak 1.65 GiB). archive_selective._daily writes an empty body inventory, points local_root at a directory that doesn't exist, and passes the raw store only for unreadable decisions. Any non-empty D2 work therefore never reads bodies, which would hit nightly production runs as well as local ones. impl-e2 is fixing it first, as one body-source binding (local mirror or R2) through readings' existing remote/body_store path, with fail-first tests that read non-empty work; then the r4-u2 rebase.

**2026-11-02T18:44:42Z**

2026-11-02 causes dry run: the model's measured 14-17.5 GiB peak (before fix 1 and the engine spill fix) doesn't fit the ubuntu-24.04 hosted runner (16 GB RAM), and the model materializes about 38 GB with spills up to 53.4 GB (profile_completeness capture_dup, being fixed upstream by engine-spill) against runner disk. A daily publish spec can't pass gate 5 until ct-ud0b's daily producer records exist. This release runs on the Mac (owner decision), so it isn't blocked; nightly hosted publishing is. Owner decision on runner capacity (larger hosted runner vs self-hosted vs further cuts) once fix 1 and the spill fix are measured.
