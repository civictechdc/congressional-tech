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

