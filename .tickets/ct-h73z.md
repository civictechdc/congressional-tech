---
id: ct-h73z
status: closed
deps: [ct-2d3k]
links: [ct-d3un, ct-qqk2]
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

**2026-10-19T19:39:00Z**

Independent review approved the byte-preserving descriptor repair at cec95671. Final five-pair admission median: 12.15 ms before, 19.73 ms after; five manual fields become one. 117 initial and 41 repair-focused checks passed. No hosted workflow was run.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch standalone).
- Grades: proposal 86 → 68, work 84 → 84.
- Problem: Regressed on main. fb9ed402 (Oct 24) removed the historical-checkout test-path fallback.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/standalone/standalone-verdicts.md:39
- Covered by: WS6 (ct-qqk2), which deletes the resume route.
- See docs/reviews/2026-10-24-ticket-audit/README.md
