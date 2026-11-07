---
id: ct-6r1i
status: closed
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

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at b20b3316. The review confirmed that the missing details are repaired at publication. It also found two acceptance-helper defects: cached proof lacked current reader/selection/environment binding, and fixed log names prevented retry after lock refusal. Both are repaired; seven isolated controls passed.

The reviewed source reference is included in local main 1a5ae01c. Remaining: The full two-way row/value/provenance/multiplicity comparison, authentic bill/vote/ballot checks and installed/hosted agreement on the final shared native release. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-6r1i/REVIEW.md).

**2026-11-07T20:43:34Z**

The three legislative Parquets on public archive `5d24699ad9fa076e3e10c894a1cb3310ab35b12e8025adcca87feca7978080c1` are byte-identical to the independently verified 11,524,996-row comparison against the pinned upstream inputs. Explorer 0.6.2 returned filtered bill actions, the exact roll call and the retained ballot for vote `101-house-2-1` and member `name:Ackerman`, including the original position and source generation. The same live Worker returned an explicit query deadline for the unfiltered `get_member_ballots` request with `{"query":{"limit":1}}`. Record the separate hosted performance gap and preserve the verified keyed ballot path.

[Published archive manifest](https://congressional-data.spicygov.ai/viewer-publications/releases/5d24699ad9fa076e3e10c894a1cb3310ab35b12e8025adcca87feca7978080c1/manifest.json)

**2026-11-07T20:46:11Z**

Scoped acceptance is complete. The exact final upstream comparison and the live vote/member-keyed ballot satisfy this ticket. The hosted limit-only request remains a separate runtime limitation.

Supply a vote or member filter for hosted member-ballot queries because unfiltered pages can time out.
