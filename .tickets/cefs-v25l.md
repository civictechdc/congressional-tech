---
id: cefs-v25l
status: in_progress
deps: []
links: []
created: 2026-10-27T15:15:26Z
type: task
priority: 2
assignee: mikewolfd
parent: cef-6q2y
tags: [engine-first, site, recovery]
---
# A7: preserve every named recovery claim in readable labels

## Acceptance Criteria

All thirteen canonical recovery kinds retain their specific claims in readable labels; existing synthetic official_substitute and unknown-kind behavior stay unchanged; table fixtures and rendered counterpart cases pass.


## Notes

**2026-10-27T15:27:30Z**

All 13 canonical claims plus synthetic official_substitute have exact readable labels; unknown-kind fallback is unchanged. Expected fixture committed before behavior. npm test:archive-unit:10 pass; npm test:archive-presentation:4 pass. Independent semi-formal code review APPROVE at534d8f54 with no findings. No registry, attachment, model or schema change.

**2026-10-27T15:50:20Z**

Engine census added two final canonical values at4d8e94dc: full_recording_recovered and explicit_retained_download_wrapper. Reopened for this narrow label-table extension; expected fixture updated before behavior. No playback, model or schema expansion.
