---
id: ct-ud0b
status: open
deps: [ct-itcg, ct-whm2]
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

**2026-11-02T20:21:07Z**

2026-11-02 measurement for the runner decision: the full model at release settings on engine b0342a7 peaked at 9.40 GiB RSS (16 GiB pool, 2 threads), under the 16 GB ubuntu-24.04 runner; the capture_dup spill drops to about 0.4 GB with the backport. Disk and runtime on a runner are still unmeasured.

**2026-11-02T20:55:01Z**

2026-11-02 train/spec-run: setup-native-runtime.py hard-codes a 120 s engine-call timeout, which would kill a hosted full model run (the local release run needed more). It must come from the job's declared limits before any hosted model or nightly run.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.

**2026-11-04T02:21:36Z**

Reopened 2026-11-03 (post-release acceptance test): automatic causes work, but the hosted nightly path cannot publish yet. Blocked by ct-r8jd (rss_gb) and ct-itcg (the daily job's canonical archive.* tables still hold v21, not the live release's inputs, so Gate 1 would refuse every nightly candidate).

**2026-11-04T02:29:12Z**

2026-11-03: ct-itcg closed (specs pinned to archive_r1b); publish binding admits with rss_gb 14. Dropped the ct-r8jd dependency: what remains there is maintenance only. Remaining here: one hosted nightly run that builds from the archive_r1b base, passes Gates 1-5 and publishes (or refuses with a recorded reason).

**2026-11-04T02:33:37Z**

2026-11-03: pushed specs (origin/main 655476f2); publish --check-binding --github-output passes locally. Not dispatched; a hosted run would fail: (1) GitHub has no archive-publish/archive-backfill/archive-maintenance environments and none of ARCHIVE_PUBLISH_ENGINE_CREDENTIALS, ARCHIVE_PUBLISH_R2_ACCESS_KEY_ID, ARCHIVE_PUBLISH_R2_SECRET_ACCESS_KEY (repo has only R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, DOCSPEC_ENGINE_CREDENTIALS); (2) spicy-regs inputs exist only under local .cache (ct-whm2). DOCSPEC_RUNTIME_ARTIFACT matches model/docspec-runtime-pin.json (b0342a73, linux-amd64 9e5cc34f). archive-jobs.yml has never run. The workflow_run trigger also needs capture-archive enabled (ct-4jms).

**2026-11-04T03:16:11Z**

2026-11-03: re-enabled archive-jobs.yml (owner decision; it had been disabled by hand 2026-10-28) and dispatched publish run 41763463814. Binding, spicy-regs fetch, runtime install with repo-wide secrets, site build and Gate 3 passed; the publisher refused 'job requires explicit host limits' (remote installs never wrote limits; watchdog peak 0.91 GiB). Fixed: .github/docspec-hosted-limits.json (10 GiB pool, 10 GiB spill, 4 threads) written by setup-native-runtime for remote installs.
