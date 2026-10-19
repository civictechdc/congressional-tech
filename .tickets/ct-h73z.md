---
id: ct-h73z
status: in_progress
deps: [ct-2d3k]
links: [ct-d3un]
created: 2026-10-19T16:40:42Z
type: task
priority: 3
assignee: mikewolfd
tags: [overlap-followup]
---
# Use original-attempt descriptor at workflow resume boundary

CLI discovery emits a validated original-attempt descriptor, but workflow_dispatch still asks operators to transcribe revision, original run, artifact ID, digest and attempt separately (.github/workflows/publish-filename-viewer.yml:11-30,99-111). That leaves avoidable resume errors after the controller fix.

## Acceptance Criteria

- Workflow resume consumes or generates the single validated descriptor without manual five-field transcription.
- Checkout exact original revision and restore exact original accepted artifact before verification/publication.
- Reject conflicts, malformed/oversize descriptor and ambiguous artifact selection before journal or publication writes.
- Preserve explicit resume authority and current scheduled no-op skip behavior.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: .github/workflows/publish-filename-viewer.yml:62:publish (workflow job). See docs/package-overlap-rescore-20261019.md for the full grade map.

**2026-10-19T19:30:46Z**

Implemented one validated resume record shared by workflow bootstrap and CLI. Exact revision/artifact,16KiB bound, duplicate/conflict/repository rejection, old/current selected test layouts and unchanged scheduled skip covered.117 local focused tests passed. Manual fields5 to1; stronger admission median13.14ms to21.67ms on5 local paired trials, not a speed claim. Awaiting independent review; docs/experiments/efficiency-debt/workflow-resume.md.
