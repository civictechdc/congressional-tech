---
id: ct-4jms
status: open
deps: []
links: [cefr-xjsp, cef-96wc, ct-tk10, ct-ud0b]
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, ops, capture, cutover, track5]
---
# T5.2: Enable ARCHIVE_CAPTURE_ENABLED and run capture-archive.yml against live url_state.parquet

Per docs/plans/engine-first-switch.md (§Second publication, item 5): enable ARCHIVE_CAPTURE_ENABLED, run .github/workflows/capture-archive.yml once against the live release's url_state.parquet, and verify created receipt lines carry stored_md5 and stored_suffix with no old-index reads.

## Acceptance Criteria

capture-archive.yml runs live against url_state.parquet with ARCHIVE_CAPTURE_ENABLED, emitting receipts with stored_md5 and stored_suffix and zero old-index reads.


## Notes

**2026-11-01T20:08:14Z**

Reopened 2026-11-01: capture-archive.yml is disabled_manually with no recorded runs, and ARCHIVE_CAPTURE_ENABLED is not set. Acceptance requires a live run.
