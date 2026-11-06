---
id: ct-6r1i
status: in_progress
deps: []
links: [ct-gi01, ct-j49p, ct-nozw]
created: 2026-11-05T23:51:57Z
type: feature
priority: 0
tags: [mcp, mcp-research-20261105, mcp-proposal-004, legislative-activity]
---
# Expose bill actions, roll calls, and member ballots in Congress MCP

Congress MCP publishes latest bill actions and embedded vote summaries. The release schema already names the pinned SpicyRegs `bill_actions`, `roll_call_votes`, and `member_votes` relations. Make their supported detail queryable and preserve the existing join keys and source provenance.

## Acceptance Criteria

- Retrieve chronological actions, roll calls, and recorded status changes by bill or date range, with stable ordering and paging. Expose member ballots keyed by vote and member when the pinned source supplies them.
- State the upstream generation, source references, coverage and exclusions for each relation. Keep vote totals, individual ballots, voice actions, and recorded status changes distinct. Preserve existing summaries and read-only SQL access.
- Compare released keys and rows in both directions against the selected upstream inputs for the supported scope. Exercise a bill with several actions, a vote with ballots, a vote outside the local bill set, and unavailable source detail. Reuse the nomination chronology from [ct-j49p](ct-j49p.md) where relevant.


## Notes

**2026-11-06T18:43:10Z**

2026-11-06 owner update: Implemented queryable bill actions, full roll calls and member ballots through normal MCP tools, preserving occurrence keys, literal dates, source provenance, stable ordering and paging. The legislative reader and comparator on main `798db35e` and inspected integration `924e3ef2` match reviewed `cffa18e0`. Exact upstream pins and expected row counts are verified. Actual retained e145 unavailable-detail stdio checks passed (0.322 GiB peak RSS), as did the prepared launcher's readiness refusal and nonblocking consumer-lock controls. These are bounded, partial acceptance checks; this session claims no full lane or final native conservation. All independent work is complete. Evidence and runnable handoff: `.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-6r1i.md`.

Keep in progress; closure is not ready. ct-082q now reports zero pending and source-freeze readiness, replacing the old baseline blocker. ct-m104 must finish current source/validation work and supply the actual native_ready manifest/result/release and one prepared selection. ct-6r1i then runs the full two-way row/value/provenance/multiplicity comparison and authentic bill/vote/ballot checks; those have not run. Final selected/public/installed agreement remains ct-m104-owned. Nothing is claimed deployed or live; indexing stays deferred.

An independent GPT-6.1 Sol/xhigh review is now running in `/root/ct_6r1i_independent_review` with no inherited conversation and all four requested skills. Verdict is pending; this new review obligation is not complete. The previous bounded validation and candidate-preparation work remains complete; actual native/selected-release gates remain open.

Independent review is in progress. No final review approval or completed release acceptance is claimed.
