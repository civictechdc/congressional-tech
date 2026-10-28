---
id: cefr-yvjw
status: closed
deps: []
links: []
created: 2026-10-27T13:54:26Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B6: clean-tree identity for raw receipt writers

## Acceptance Criteria

Raw writers record clean HEAD and SHA256 of uv.lock; dirty tracked, staged and untracked files refuse before storage connection; source manifest shares identity; focused tests pass.


## Notes

**2026-10-27T13:55:35Z**

Implementation and contracts committed; focused runner test_writer_identity.py, test_capture_source_manifest.py, test_pipeline_raw.py: 21 passed. Pending independent review; capture workflow must move native-runtime-check.json and raw-capture-source-manifest.json to ignored output paths before strict clean manifest recording.

**2026-10-27T13:55:51Z**

Correction: cxb_b6_focused.log records 18 passed in 3.99s, not 21. The implementation commit body had an incorrect count; the retained runner log is authoritative.

**2026-10-27T14:27:58Z**

B6 workflow repair: isolated local exact-commit application clone plus uv sync --locked; capture validates/fingerprints that same clean environment before writes and keeps report/runtime/inventory artifacts external; weekly save executes clean Python -I after snapshot persistence. Contract c9afcee6; final focused workflow/identity/boundary group 99 passed in102.22s (cxb_focused_final.log), local fake installs/HTTP writers and local bare Git fixture only. No hosted job, credentials, native pin change, or network write. Independent architecture review pending.

**2026-10-27T14:34:20Z**

B6 local done: identity18pass; workflow99pass; independent code APPROVE (b6-workflow-review), architecture APPROVE+50pass (b6-workflow-arch). Dirty-root blocker resolved56265ada by clean exact-commit clone/locked env and external artifacts. Live hosted runs and B15 import/token remain owner gates, not exercised.

**2026-10-28T01:41:57Z**

Retro-review B1 fixed: contracts d345489f failed7 before behavior4bd92403; project focused31passed9.14s. Independent CODE and ARCH APPROVE no findings, reports run2/review-b1-{code,arch}/review.md. Setup/body/receipt failures cause zero push calls; push failure retains raw. Local bare Git/store only, no hosted/live operation.
