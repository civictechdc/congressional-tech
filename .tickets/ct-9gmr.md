---
id: ct-9gmr
status: open
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
