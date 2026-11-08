---
id: ct-4kuo
status: in_progress
deps: [ct-9s7b]
links: []
created: 2026-11-05T23:51:57Z
type: feature
priority: 0
tags: [mcp, mcp-research-20261105, mcp-proposal-002, transcript-reliability]
---
# Read hearing transcript and caption text by event in Congress MCP

Researchers can read a known document through `get_document(section='text')`. Add event-based access to the official transcript, committee transcript, and complete caption sources already discoverable from a meeting. Reuse the verified body reader in [ct-o7t4](ct-o7t4.md) and the meeting inventory in [ct-9s7b](ct-9s7b.md).

## Acceptance Criteria

- Expose `get_transcript(event_id, kind?, offset?, limit?)`. Identify available sources by kind, provenance, and stable reference. Let callers select a specific source when several match.
- Return page or text windows for official and committee transcripts and timestamped cues for complete caption tracks. Return paging information and enough source detail to reopen the same text. Resolve retained files and supported playlists on the server.
- Keep body verification, archive access limits, and bounded responses. Report partial or unavailable material explicitly. Exercise a transcript-only hearing, a caption-only hearing, multiple sources, and an incomplete track through the MCP tool.


## Notes

**2026-11-06T18:43:10Z**

2026-11-06 owner update: Local get_transcript discovers and selects official, committee and caption sources, returns verified bounded text or timestamped cues with paging, reopens exact citations, and keeps partial/unavailable material explicit. At 798db35e, all 86 app files match reviewed cffa18e0; the installed-asset audit verifies 20 modules, all 70 dependencies and Poppler 26.06.0. Source-bound evidence reuses the retained full MCP app lane (191 passed, zero skips) and focused/native-fixture checks for transcript-only, caption-only, multiple-kind and incomplete-track cases, paging, timing and citations. No new full lane or authentic final-release consumer run is claimed. Independent preparation is complete; the source-read probe and runnable command are in [the owner handoff](../.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-4kuo.md).

Keep in_progress; closure_ready is false. ct-m104 owns final source qualification, the sole native build and prepared/selected release. ct-9s7b owns its site-label repair, native inventory reconciliation and selected-release site checks. This owner's authentic event 338785 installed-source reads, continuation and exact citation reopening remain not run until native_ready. The old 144,161-pair HTML backlog is resolved; the shared final candidate/selection and live acceptance remain absent. Indexing stays deferred.

User-requested independent review is running as /root/ct4kuo_blind_review (GPT-6.1 Sol/xhigh) using greybeard, etl-workflow, evolutionary-refactoring and semi-formal-code-review. Review is static/read-only; verdict and any scoped fixes remain pending.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at b20b3316. The review found that the acceptance probe could silently skip committee transcript reads when no automatic candidate fit its 2 MiB cap. The probe now requires successful official, committee and caption reads and records unverified kinds. Six focused decision controls passed; these are probe checks, not actual-release consumer evidence.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Authentic source reads, continuation and exact cue/page reopening on the final native release, followed by selected site/MCP readback. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-4kuo/REVIEW.md).

**2026-11-08T03:59:58Z**

November 7: integrated the independently reviewed PDF input-transfer repair 2288e5ef. The decoder now keeps one complete stdin transfer running while the caller checks cancellation and its deadline. Previously, the first 20 ms wait could expire during startup and the next communicate call omitted the remaining input, leaving the decoder waiting for EOF. The existing finally path still kills and reaps the owned process family before joining the transfer worker.

The delayed-start regression reproduced the failure before the repair and passed afterward. The retained focused run passed 30 tests; its two environment-dependent Poppler failures passed with pinned Poppler 26.06.0. Those logs predate the source commit and are not a combined-lane or package acceptance claim. Independent review approved source integration. [Review](../.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-m104/reader-release-0.6.3/DECODER-REVIEW.md).

Keep in_progress. The corrected normal-reader check against the two authentic public PDFs is awaiting its current sandbox approval. It must reopen citations and compare source release, body, location and text. Run the exact combined MCP lane after the reader dependency boundary is settled, then build and qualify one 0.6.3 reader release with the ballot repair. Public Explorer 0.6.2 and archive 5d24699ad9fa remain unchanged. No archive rebuild is required for these reader changes.
