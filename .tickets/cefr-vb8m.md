---
id: cefr-vb8m
status: in_progress
deps: []
links: []
created: 2026-10-28T21:27:26Z
type: bug
priority: 1
assignee: raw
---
# D1: distinguish reference and saved-record lines from acquisition failures

Implement owner212226 finite family/shape line-kind registry, reference and saved-record outcomes, entry status_code fallback only without line/item final status, and URL-state exclusion; preserve explicit acquisition facts and refuse unknown record-only shapes.

## Acceptance Criteria

Fixture first covers every registry kind, explicit failure and acquisition preservation, per-item lists, unknown refusal and final-status priority; focused runners and one independent code review pass. New D1 generation/comparator and downstream D3/model/E4 qualify serially when owner resources allow.

