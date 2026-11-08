---
id: ct-28tj
status: closed
deps: [ct-4kuo]
links: [ct-m704, ct-krdp, ct-082q]
created: 2026-11-05T23:51:58Z
type: feature
priority: 2
tags: [mcp, mcp-research-20261105, mcp-proposal-014, search-retrieval]
---
# Return stable citations for PDF pages, caption cues, and witness statements

Use the existing release-bound document references, PDF page and offset results from [ct-o7t4](ct-o7t4.md), selected testimony from [ct-082q](ct-082q.md), and cue timing from [ct-4kuo](ct-4kuo.md). Give researchers a consistent way to cite and reopen a passage.

## Acceptance Criteria

- Return a stable source reference and an appropriate location for a PDF page, a timestamped caption or transcript cue, or a witness statement. Carry release and body identity where available, plus the witness occurrence when the source supports that association.
- Reuse existing source and body identities across text retrieval and search results. Define how a reference resolves against its pinned release and reports an unavailable or different source.
- Round-trip one reference of each supported kind to the original evidence. Reuse the passage check in [ct-082q](ct-082q.md) when the locator is unchanged. Check a changed body, an ambiguous witness match, and a missing source so references retain their original meaning.


## Notes

**2026-11-06T18:43:10Z**

2026-11-06 owner update:

Stable citations preserve release/body identity and exact PDF page, HTML passage/selected-block, and caption cue/timing locations, with explicit witness occurrence or ambiguous attribution. The app remains byte-identical to reviewed cffa18e0; retained validation is 191 passed (full app lane) plus independent round trips and eight wrong-value refusal plants. Independent work is complete: the normal stdio probe and report-bound plan builder are runnable, with shared-lock, identity and disk guards; six preparation checks and four final smoke/guard checks passed. Evidence: parallel-sessions/ct-28tj/RUN.md and independent-audit-final-20261106/checks.json under the durable mcp-research-20261106 root. No new application commit or live-delivery claim.

Keep in_progress. HTML baseline/daily adoption is now locally qualified; the old blocker is stale. ct-m104 owns the still-unavailable final native candidate/shared selection and selected release. ct-082q and ct-4kuo must supply passed same-release HTML/PDF/caption reports before actual citation and final witness round trips can run. Corpus-search citations remain deferred with ct-m704.

A fresh independent four-skill review is running under agent /root/ct_28tj_blind_review. Implementation preparation is complete; review findings and any required corrections remain pending. Keep closure_ready=false.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at 51909188. Caption citations now validate witness membership and optional attribution through the same checks in generation and both resolver paths. A normal MCP stdio control reproduced the unsupported-occurrence bug; 25 focused checks passed after repair.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Final combined-source qualification, fresh software artifacts, actual shared native citation/witness round trips and selected public readback. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-28tj/REVIEW.md).

**2026-11-08T11:02:40Z**

Hosted Explorer 0.6.3 is deployed on both replicas against archive 5d24699ad9fa. PDF first/continued citations and the event 338785 caption citation round-trip to the same original passages. The Higgins statement preserves its exact witness occurrence, source-association attribution and text digest. Retained changed-body, ambiguous-witness and missing-source refusal controls remain valid; ct-4kuo is closed.

Evidence: .cache/archive-release/releases/congress-mcp-0.6.3-20261107/hosted-acceptance-01/ and .cache/archive-release/mcp-research-20261106/parallel-sessions/ct-28tj/live-5d24699-witness-01/.
