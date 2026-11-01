---
id: ct-vnkf
status: closed
deps: []
links: [ct-cov3]
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, ci, jobs, maintenance, track3]
---
# T3.2: Bind active CI job specs (.github/archive-jobs.json & model/jobs/*.pending.json)

Implement the CLI entry points for backfill and maintenance (wiring packages/congress_api/src/congress_api/retention/raw_verifier.py, packages/viewer_publication/src/viewer_publication/archive_maintenance.py, and packages/congress_api/src/congress_api/lake/maintenance.py), replace model/jobs/publish.pending.json, model/jobs/backfill.pending.json, and model/jobs/maintenance.pending.json with active job specs, and update .github/archive-jobs.json.

## Acceptance Criteria

model/jobs/publish.json, backfill.json, and maintenance.json replace the *.pending.json files, .github/archive-jobs.json points to active specs, and CLI entry points pass tests.


## Notes

**2026-10-30T19:28:54Z**

Reopened per Greybeard parity audit: (1) model/jobs/maintenance.json omits raw_verification and lake_maintenance configuration sections; (2) .github/workflows/raw-source-tables.md:10,44 references viewer_publication.archive_maintenance_job instead of viewer_publication.archive_maintenance; (3) apps/site/FILENAME-VIEWER.md:25 states /dashboard/ redirects to /archive/ whereas /dashboard/ coexists for coverage/issues views.

**2026-11-01T03:12:32Z**

Added raw_verification and lake_maintenance configuration sections to model/jobs/maintenance.json and archive_maintenance.plan(), updated .github/workflows/raw-source-tables.md to reference viewer_publication.archive_maintenance, and updated apps/site/FILENAME-VIEWER.md to state that /dashboard/ coexists for coverage and issues views. Verified 87 passed.

**2026-11-01T10:38:19Z**

Independent Validation Audit (2026-11-01, validator 2366732b):
- Verdict: PASS-WITH-CAVEATS (3/3 ACs met; all `*.pending.json` files removed; `run-archive-job.py {publish,backfill,maintenance} --check-binding` exits 0).
- Remaining work before closure:
  1. [Priority 1] In `packages/viewer_publication/src/viewer_publication/archive_maintenance.py:453-477` (`execute`), validate that `raw_verification` input files (`inventory`, `baseline`, `scope` in `model/jobs/maintenance.json:45-50`) exist—or run `verify_raw` preflight—before calling `maintain_releases` with `execute=True`, so a missing local verification input cannot abort the run after destructive release deletions have already occurred.
  2. Commit working-tree changes.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 5 Engineer (4c90d67e, 99% confidence) across Round 1 & Round 2:
  1. Added `_prepare_raw_verification_inputs` (`archive_maintenance.py:428-461`) and reordered `execute()` (`archive_maintenance.py:489-526`) so `raw_verifier.verify(...)` runs and enforces `if execute and not verified.get("valid", False): raise RuntimeError("raw verification failed; refusing release pruning")` BEFORE opening `ArchiveMaintenanceStore` or executing destructive `maintain_releases(...)` deletions (`test_phase2_release_pruning.py:204-318`).
  2. Synced `model/jobs/publish-model.json` and `model/jobs/publish.json` (`sha256: 7de6a4a1a8396bb1e0be11be91d746d8af6efbd0421ef681efafe8f4281dc198`, `size: 2582`); all 3 `run-archive-job.py {publish,backfill,maintenance} --check-binding` checks exit `0`.
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (99%), Green Team PASS (100%), Greybeard PASS (99%), Evolutionary Refactoring PASS (99%).
