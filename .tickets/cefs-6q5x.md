---
id: cefs-6q5x
status: closed
deps: []
links: []
created: 2026-10-27T18:47:22Z
type: task
priority: 2
assignee: site
---
# E3 source and document ID golden vectors

Owner handoff via lead184415. Preserve current ID code; cover exact serialization, missing fields, Unicode, ordering and source fallback.

## Acceptance Criteria

Committed literal compact JSON and SHA-256 vectors reproduce through current source_identity and compute_document_id; fixture format agreed with engine for E2 SQL parity


## Notes

**2026-10-27T19:01:09Z**

b9b1f735:31fixedvectors and32focusedchecks pass. Independent CODE and ARCH reviews APPROVE with no findings. Engine agreed fixture path/shape and owns future E2 native SQL consumption; no native parity claim made here. Existing production ID code unchanged.

**2026-10-27T20:11:05Z**

Corrected ordinary logical body-key .gz inputs865b5de8;32current-ID reproduction tests pass; production formulas unchanged. Final c1713681 full11672passed with exact36baseline identities unchanged. Corrected immutable fixture delivered shared/id-vectors-865b5de8; native E2 parity remains engine work.
