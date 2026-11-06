---
id: ct-hnpc
status: in_progress
deps: [ct-6r1i]
links: [ct-9xfg, ct-nozw]
created: 2026-11-05T23:51:57Z
type: feature
priority: 0
tags: [mcp, mcp-research-20261105, mcp-proposal-005, legislative-activity]
---
# Add a dated legislative activity feed to Congress MCP

Let researchers ask what happened in a week without writing SQL. Build on the published legislative events from [ct-6r1i](ct-6r1i.md) and other supported event sources.

## Acceptance Criteria

- Expose `get_activity(since, until?, chamber?, committee?, topic?, limit?)`. Define date-window boundaries, supported event types, filter meanings, deterministic ordering, and paging.
- Return the event date or timestamp with its precision, type, subject, source reference, and applicable coverage limits. Derive committee and topic matches from supported published associations.
- Exercise a representative week across supported event types, a filtered week, a valid empty interval, and an interval with unavailable coverage. Compare sampled events with their source rows and retain distinct events that share a date.


## Notes

**2026-11-06T18:43:10Z**

2026-11-06 owner update: `get_activity` is implemented locally with six dated event types, supported chamber/committee/topic filters, source references and deterministic paging. At verified main `798db35e041516eaf582accc5fe04e72d481448f`, the reviewed API and authentic chronology bytes remain unchanged, so retained independent association/time plants still apply. Independent work is complete: the week-planning control found all six types, and eight bounded checker refusal/readiness controls passed (0.123 GiB peak; `.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-hnpc/independence-audit-02/report.json`). No new full lane, native-release or live acceptance is claimed.

Keep in_progress; closure_ready=false. ct-m104 must supply the frozen native release and prepared selection, ct-6r1i must pass complete row/value/provenance/multiplicity conservation, and the actual week/filter/empty/unavailable/order/paging checks must then run. ct-m104 owns final installed/hosted readback. The old 144,161-pending-HTML blocker is resolved. Runnable continuation and exact evidence are in `parallel-sessions/ct-hnpc.md`.

Requested follow-up: an independent GPT-6.1 Sol/xhigh reviewer (/root/ct_hnpc_independent_review) is now reviewing the exact main source and cached acceptance scripts with greybeard, etl-workflow, evolutionary-refactoring and semi-formal-code-review. No verdict has been returned yet.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at 82c7f333. Nomination activity coverage no longer treats received-date bounds as bounds on later actions. Receipt-date research and raw event values are preserved. The ordinary-MCP regression failed before repair; all 10 focused legislative checks passed afterward.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Final native output, ct-6r1i conservation, actual week/filter/empty/coverage/order/paging checks and installed/hosted readback. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-hnpc/REVIEW.md).
