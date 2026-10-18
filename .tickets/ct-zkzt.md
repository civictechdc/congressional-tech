---
id: ct-zkzt
status: closed
deps: []
links: [ct-ylaw, ct-o24q, ct-rrfm, ct-hm4b, ct-m59w]
created: 2026-10-18T19:21:16Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Publish the recovery index accepted during preparation

Recovery-only preparation computes index_recoveries, discards the result, and artifacts the large filenames/groups inputs. Publication computes the index again from those same local inputs.

Source: scripts/viewer_publication_attempt.py:57-69 and :238-246.

## Acceptance Criteria

Accept computed status bytes and their digest in the preparation inventory. Resume verifies those bytes and original input identities, preserves fresh protected-input checks and the conditional viewer write, and performs no second index scan. Mappings changed after preparation and stale preparations must be rejected.

<!-- grade-followup:start -->
## Grade review follow-up

prepare.build, recovery_for_publication and select_recoveries, including full release status derivation where applicable.

- Accept status bytes/digest and original file/source/viewer/mapping identities; publication and resume do no second index scan. Mappings changed after preparation refuse; ordinary changed-mapping preparation remains supported. Keep current mutable checks, original pointer condition and public proof.

[Function scope and checks: 7 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:707). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:27:13Z**

Full and recovery preparation now accept recovery-prepared.json into inventory, binding original source manifest/files/catalog and exact accepted mapping presence/raw digest. Recovery artifacts contain only manifest+accepted status instead of large indexing inputs. Publish/resume consume verified accepted status and never rerun index_recoveries; new mappings still prepare normally, later changes refuse before writes. Explicit no-second-index tests include recovery runner death and full publication.116 tests+2subtests plus final40 targeted tests pass.
