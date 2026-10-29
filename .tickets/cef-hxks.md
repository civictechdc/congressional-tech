---
id: cef-hxks
status: in_progress
deps: []
links: []
created: 2026-10-29T04:56:14Z
type: bug
priority: 0
assignee: engine
---
# Require an explicit private-bucket choice for runtime distribution

Lead confirmed raw bucket is public; uploader defaults can expose private DocSpec binary. Require explicit bucket in CLI and helper APIs; replace misleading examples and recut private runtime packet. No upload has occurred.

## Acceptance Criteria

Omitted bucket refuses before binary reads or network effects; explicit private descriptor/upload paths keep exact identity/readback tests; focused project runners and one review approve.

