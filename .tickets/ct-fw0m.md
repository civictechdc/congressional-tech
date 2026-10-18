---
id: ct-fw0m
status: closed
deps: []
links: [ct-3djs, ct-1dsp, ct-ylaw, ct-gesp, ct-m59w]
created: 2026-10-18T19:44:01Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Carry verified catalog files across publication stages

Recovery Store adapters copy/hash verified files into another directory, and R2Store.put_derived_file recomputes SHA256 after its caller computed it. Those costs accumulate across selection, history and upload.

Sources: dispatch_corpus_recovery_publication.py:218-230; r2.py:313-355.

## Acceptance Criteria

Give each staged file an explicit owner and lifetime. Reuse an exact in-process identity to remove duplicate copies/hash passes; record reduced bytes copied/hashed and scratch. Changed files or a fresh process require validation. Preserve transport MD5/ETag checks, history collision checks, retained failure evidence and caller cleanup.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 8 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:327). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:18:42Z**

VerifiedFile carries exact process-local custody. Recovery save_derived retains exclusive same-filesystem links with caller-owned lifetime, checked-copy fallback across filesystems and retained partial evidence. R2 issued proof skips duplicate SHA while preserving complete transport MD5/ETag; history collisions still read back exact bytes. Fixture records 29-byte retention: zero extra copied/hashed payload/scratch allocation; 700-byte upload: zero repeated SHA bytes, 700 MD5 bytes. LocalStore deliberately keeps independent copy because caller may rewrite build paths. 134 tests + 5 subtests pass; receipt tracked.
