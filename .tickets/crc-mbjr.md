---
id: crc-mbjr
status: closed
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


## Notes

**2026-10-28T09:51:44Z**

Local done: contract18 red/1 pass ->52 focused passes with no client on bad approval, exact canonical types, bounded metadata, same-size drift refusal, create-only retry and full readback. Independent review APPROVE in codex-release2/review-window/review-fix-3e7e5d20.md; uploader/tests identical between CI94bd and landing3e7e. Live upload remains lead-only after final runtime qualification.
