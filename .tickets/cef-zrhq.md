---
id: cef-zrhq
status: closed
deps: []
links: []
created: 2026-10-27T18:29:08Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine-first, C0]
---
# Require one explicit native runtime before the offline test lane

## Acceptance Criteria

production-offline refuses before pytest with one actionable setup error for missing/invalid DOCSPEC_JOB_CONFIG; a verified pinned local runtime passes. No silent skip or implicit scratch default, remote/credential configuration refused before credential loading.


## Notes

**2026-10-27T18:34:41Z**

17 focused runner fixtures pass and a real invocation without DOCSPEC_JOB_CONFIG exits once before pytest with an explicit setup error. CODE and ARCH APPROVE at 3febd5ea. The runner requires a pinned local config and rejects remote/credentials before loading; no scratch default or silent skip. F1 must supply an approved platform runtime, whose live distribution remains gated.
