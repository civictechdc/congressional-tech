---
id: cefs-6q5x
status: in_progress
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

