---
id: ct-4nyy
status: closed
deps: [ct-jo8n]
links: [ct-3li2]
created: 2026-10-20T22:15:53Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Use native exports only after news rights and expiry filtering

The news client exposes ExportSpec but no actual export caller uses it. Native export authorizes named columns and every row in one retained group; it does not apply news C5 restrictions or expiry rules. Connect the existing authorized export path to native completion and replay.

## Acceptance Criteria

- Start with one exact published news release and apply maintained analysis/export.py policy, including restricted/metadata-only content, derived copies and capture expiry.
- Export only the authorized exact version and column allowlist, preserving nested values while removing private field metadata and credentials. Do not publish native object URLs as evidence of public authorization.
- Decode output independently and test expiry boundaries, expired captures referenced by versions, old export reads and lost-response replay without rewriting completed output.
- Keep archive/viewer routed assets and review bindings with their current owner; a native whole-group export is optional and never required for a routine incremental update.


## Notes

**2026-10-20T22:15:54Z**

2026-10-20 adoption review: packages/news_lake/src/news_lake/storage/docspec_backend.py (primary checkout). Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.
