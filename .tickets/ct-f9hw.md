---
id: ct-f9hw
status: open
deps: []
links: []
created: 2026-11-02T11:10:10Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [raw, privacy, receipts, phase2]
---
# Public raw receipts carry absolute local filesystem paths

plan-e1-captures census 2026-11-02: file_references[].original_path holds 279,549 absolute local /Users/... values (415,134 relative, 46,365 missing) in receipts served from the public origin. Receipts are immutable, so existing lines stay. Cause: importers recorded their local path instead of a path relative to the retained root. Measure: .cache/rounds/r1b/e1/measure/.

## Acceptance Criteria

- Every receipt writer emits relative paths only, refused at write by a test (impl-e1, r1b-e1).
- The data model states whether original_path is public and in which form; captures.original_path keeps relative values only.
- The owner decides whether existing public receipts need a superseding redaction record or stay as written; the decision is recorded.


## Notes

**2026-11-02T13:54:36Z**

Owner decision 2026-11-02: leave existing receipts as written. Exposure is the username (already public as the GitHub login) and folder layout (/Users/mikewolfd/Work/..., /Users/mikewolfd/hearing-text/...); no secrets found. Writers now refuse absolute paths (impl-e1, r1b-e1). Origins: assemble_raw_archive.py (0ea63070, 2026-09-30, about 636k lines), the old receipt builder (deleted in b46cbf58) for October download runs, and corpus-recovery runs up to 2026-10-16; none after 10-16. Close when r1b-e1 merges.
