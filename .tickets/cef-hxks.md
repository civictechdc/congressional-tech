---
id: cef-hxks
status: closed
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


## Notes

**2026-10-29T05:06:55Z**

Configured RED: four missing-bucket refusals failed before fix, three prior cases passed. GREEN: 62 maintained runtime publication, wrapper and setup cases passed under 1 GiB. Same independent CODE review closed wrong public bucket and private-wrapper durability findings; private v2 sealed for preparation only. No upload, variable change or Linux qualification occurred.
