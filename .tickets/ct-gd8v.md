---
id: ct-gd8v
status: in_progress
deps: []
links: []
created: 2026-10-20T08:12:03Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, preservation]
---
# Bind raw adoption to exact retained source versions

The complete input scan verified local hashes and original R2 versions, but the operational importer currently discards the remote capture/state versions. A legacy writer could change those checkpoints while native candidates are being prepared.

## Design

Carry exact capture/state source keys and versions through the existing adoption input receipt; bind them to the operation and check them before preparation and before final selection. Reuse the existing version reader and before_publish callback. Source checks detect drift; retire or quiesce legacy writers before cutover because checks on separate object keys are not an atomic fence.

## Acceptance Criteria

Local tests prove changed source versions refuse before any preparation or final selection, stable pins preserve all values and completed retry remains idempotent. Independently review. Record that legacy writers are inactive before production cutover; no new journal or workflow dispatch.

