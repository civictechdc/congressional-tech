---
id: ct-jl1m
status: closed
deps: []
links: [ct-ylaw, ct-1dsp, ct-sv16]
created: 2026-10-18T19:44:01Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Define and verify publication writer coordination

active_cloud_writers inventories capture runs only. Its freshness window is an observation, not a lease; shared selectors still rely on conditional writes. Repeated full guard checks also cross unchanged local custody.

Sources: recovery_guards.py:19-40,86-118; dispatch_corpus_recovery_publication.py:27,177-180.

## Acceptance Criteria

Document each maintained writer, shared key, lock/condition and required exclusion. Exercise conflicting writers, stale/slow/malformed inventories and changes between observation and selection. Keep conditional writes and fail-closed refresh. Remove duplicate local rehashes only within unchanged custody; measure guard calls. Add stronger coordination only where this analysis proves it is required.

<!-- grade-followup:start -->
## Grade review follow-up

check_recovery_inputs and publish.guard describe the freshness cut point for separate source/accepted/viewer reads.

- Correct the claim that reading pointer last excludes all concurrent changes. Keep original viewer compare-and-swap and test relevant interleavings; state which cross-object changes remain outside atomic authority instead of claiming a transaction.

[Function scope and checks: 7 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:442). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:22:54Z**

Documented maintained writers/shared keys/lock and condition authority; corrected pointer-last cross-object transaction claim. Separate-source-read interleaving test explicitly demonstrates observation cut point while original viewer CAS remains. Guard local unchanged-custody reuse reduces2 hashes to1 across1000immutable checks+next sharedcommit; fresh cloud/protected checks remain2.51focused tests+2subtests pass incl malformed/stale/slow inventories, failed-refresh invalidation, restored-mtime same-size mutation and conflicting writers.
