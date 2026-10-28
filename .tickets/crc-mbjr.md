---
id: crc-mbjr
status: in_progress
deps: []
links: []
created: 2026-10-28T09:13:05Z
type: bug
priority: 0
assignee: mikewolfd
---
# Require the approved runtime identity before upload

## Acceptance Criteria

Expected descriptor is bounded and compared with exact local identity before client creation or PUT; changed bytes and malformed descriptors fail; create-only verified readback passes with a local fake; owner window uses the guarded checkout and review passes

