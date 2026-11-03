---
id: ct-9gmr
status: closed
deps: []
links: [ct-77zb, cef-96wc, ct-1mbc, ct-kw9b, ct-pocg, ct-kunv, ct-uupp]
created: 2026-11-01T17:43:18Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [etl, backfill, viewer-publication, phase2]
---
# Run selective backfill and release through the existing archive jobs

publish_v21 was built with ad hoc /private/tmp/publish_v* scripts outside the guarded controller. Owner decision 2026-11-01: extend the checked-in jobs rather than add a CLI, and make no further live publishes from scratch scripts. Parser-version selection moved to a separate ticket.

## Design

1. Reuse archive_backfill_job.py, capture_backfill.py and archive_controller.py resume.
2. Add predicate-scoped recomputation for captures (receipt predicate plus capture_backfill_guard.validate_generation), filename_readings (URL predicate) and D4 (meeting_records and appearance_records).
3. Use a gitignored .cache/archive-release/ workspace.
4. Coordinate replay planning with ct-pocg; do not build a second metadata replay path.

## Acceptance Criteria

- A narrow parser fix runs through a checked-in job spec with no scratch script.
- Unaffected rows are reused, and the combined output passes the guard and all model invariant suites.
- Resume works after an interrupted run, with unit tests in packages/viewer_publication/tests/.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-a5550c04138214670 @ b3c4aa3c. Review verdict: merge, stay open. Open: reconcile and check_scratch mutants survive, so add tests; the checked-in spec is blocked, so run C7 (40 GiB free before start, up to 64 GiB scratch); remove re-stamp when ct-deh9 wires.

**2026-11-02T14:50:56Z**

2026-11-02 (lead): green-e2 approves r1b-e2 at 8240567c for code; acceptance is unmet until backfill-selective runs on real data. archive-jobs.json has no rss_gb (all archive jobs refuse on main), and legacy Senate state lacks error markers; both sent to impl-e2.

**2026-11-02T16:28:57Z**

2026-11-02 (lead): impl-e2: r1b-e2 rebased onto d5574752 at 2ace3363, r1b-e2-map at f37e55ea; red-e2's 7 items done (the != to < mutant is equivalent); green's (b) and (c) done; (a) archive-jobs.json rss_gb stays unset until R3 measures peaks, and must be set before the merge to main. Integration conflict: the e1 guard read a v1 registry; the guard now accepts only the current mapping unless explicitly overridden (fix in progress).

**2026-11-02T16:30:23Z**

2026-11-02 (lead): r1b-e2 (6141a794) and r1b-e2-map (80b7ff85) merged into integrate-round1 by fast-forward (23 commits). Before the merge to main: archive-jobs.json rss_gb must be set from measured peaks (green-e2 gap a).

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
