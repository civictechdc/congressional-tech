---
id: ct-oh9y
status: in_progress
deps: []
links: [ct-t915, ct-gi01, ct-irxg]
created: 2026-11-05T23:51:58Z
type: feature
priority: 1
tags: [mcp, mcp-research-20261105, mcp-proposal-009, interface-hardening]
---
# Separate reported meeting status from verified outcomes

Build on the publisher status and `not_held` correction in [ct-n61r](ct-n61r.md). Researchers need to distinguish a scheduled meeting from evidence that it took place or was canceled.

## Acceptance Criteria

- Expose the publisher-reported status and an independently supported outcome separately through meeting discovery and lookup. Represent held, canceled, and unknown outcomes with the supporting source and reason when known. Retain contradictory publisher observations.
- Use shared producer evidence for the outcome. Keep unsupported scheduled and stale notices unknown. Preserve date-specific scope for rescheduled meetings and show the same meanings in MCP and the site.
- Verify a scheduled-only meeting, a documented sitting, a supported cancellation, and conflicting or rescheduled evidence against their sources. Check that older releases surface unavailable outcome evidence and preserve their publisher status.


## Notes

**2026-11-06T17:17:09Z**

Acceptance preparation on 2026-11-06: exact outcome/model, MCP and site source identity to reviewed cffa18e0 is recorded in .cache/archive-release/mcp-research-20261106/parallel-sessions/ct-oh9y/preparation.json; retained 191-pass full app lane reused. Normal stdio discovery/lookup and normal site reader/display both preserve actual e145 event110924 Postponed status with outcome evidence unavailable (old-real-mcp.json, old-real-site.json). Site retry passed at1.87GiB RSS after retaining the initial1.5GiB watchdog stop. Independently recovered21 of29 selected original meeting records;8 exclusions explicit. The exact curated live source includes actual start/end times for110924 on2020-07-17, beyond a video locator. No source edits or indexing. Actual final native and selected-release outcome controls remain pending ct-m104; ticket stays in_progress.

**2026-11-06T18:43:10Z**

November 6, 2026 owner audit: independent preparation is complete; the newly requested blind review is running. At integration commit 924e3ef2, all 11 outcome-related files and the whole MCP app still match reviewed cffa18e0. The retained full app lane passed 191 tests with no skips; producer and meeting-fixture checks remain partial. Normal MCP discovery/lookup and site reader/display passed on retained e145 event 110924, preserving Postponed while reporting outcome evidence unavailable. Five dated controls have 27 hash-verified publisher/print originals plus the original live-video snapshot. The fresh audit found no owned worker or waiter and passed source, custody and readiness-guard checks. No new native or public-release acceptance is claimed.

Remaining: the sole root/ct-m104 release must integrate the independently qualified ct-082q/ct-irxg planning source and 64 MiB/batch-1 configuration at 1498c06c, 6e42b5aa and d2ec0211, then transition the input pins. That work is source-freeze-ready: 192,959 selected, zero pending, with unchanged 53.46 s and changed-head 50.62 s controls passing. ct-m104 then supplies the ready native release and shared MCP selection for the source comparison, wrong-value plant and normal-consumer checks, followed by selected public readback. Keep in_progress; closure is not ready. Evidence and command: .cache/archive-release/mcp-research-20261106/parallel-sessions/ct-oh9y.md.

Fresh independent static review of 924e3ef2: REQUEST CHANGES, high confidence. It found discarded publisher observation history and an undated curated held override. Both require scoped producer repairs and focused regression controls; the owner is preparing an isolated commit and same-reviewer delta check. Keep in_progress.

Independent review: REQUEST CHANGES; current owner state: completed changes requested. These findings remain open until repaired and rechecked. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-oh9y/REVIEW.md).
