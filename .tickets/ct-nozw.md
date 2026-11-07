---
id: ct-nozw
status: closed
deps: []
links: [ct-hnpc, ct-9xfg, ct-m94a, ct-6r1i]
created: 2026-11-05T23:51:58Z
type: feature
priority: 2
tags: [mcp, mcp-research-20261105, mcp-proposal-015, interface-hardening]
---
# Expose ready-to-run congressional research queries in MCP

Build on the current scalar filters and published relationship recipes. Make recurring research queries callable with named parameters and reuse the activity feed for cross-collection event timelines.

## Acceptance Criteria

- Support recent bills, pending nominations, hearings by committee, and legislation by subject without requiring callers to write SQL. Document filter meaning, date and status fields, supported coverage, and paging.
- Reuse the maintained recipe and query paths. Return canonical IDs, source references, and explicit missingness for each result set. Use published subject associations and status evidence.
- Compare each named query with its underlying release rows. Exercise ambiguous committee or subject input, an empty result, and a collection with unavailable coverage.


## Notes

**2026-11-06T16:54:35Z**

Bounded source/recipe preparation complete. Source-proven nomination coverage wording gap repaired on isolated branch codex/ct-nozw-recipe-coverage-20261106 at b4741504: metadata now states that local nomination profiles are referenced by archive documents or meetings, and pending means a known nonterminal latest action in the snapshot. Three focused production-offline checks passed (partial, 2 of 500 lane files); measured peak 0.50 GiB RSS. Exact commit, patch, source identities, authentic source-only status counts and prepared normal MCP row comparator are retained under .cache/archive-release/mcp-research-20261106/parallel-sessions/ct-nozw/. ct-m104 must integrate before source freeze. Actual shared native recipe acceptance remains pending ct-082q baseline settlement and ct-m104 native_ready selection; final same-release installed/hosted readback stays with ct-m104. Ticket remains in progress; no indexing or release deployment claimed.

**2026-11-06T18:43:10Z**

2026-11-06 owner update: independent work is complete. The maintained MCP recipes cover recent bills, pending nominations, committee hearings and subject legislation. Source correction b4741504 is already integrated into main via cce7733f (verified at main798db35e). It clarifies the referenced nomination-profile coverage and the snapshot meaning of pending. Three focused production-offline checks passed (partial, not a full lane), peaking at0.50GiB RSS. Exact evidence and the runnable normal-MCP comparator are retained under parallel-sessions/ct-nozw/.

Keep in_progress; closure_ready=false. ct-m104 must provide the qualified shared native selection, then the four-recipe comparisons must pass against its actual rows. Reuse ct-6r1i conservation and ct-hnpc activity proof; ct-m104 owns exact final installed/hosted readback. Source integration and the old HTML-baseline blocker are resolved. No final native acceptance or live delivery is claimed.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at b4741504. The source and corrected acceptance harness have independent approval. Review found and repaired a paging variable that overwrote the call function, checks that ignored extra occurrences, and failed retry after lock contention. Controls now cover paging, nulls, multiplicity/order and same-process lock recovery.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Actual shared-native four-recipe comparisons, ct-6r1i conservation, ct-hnpc activity checks and final installed/hosted readback. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-nozw/REVIEW.md).

**2026-11-07T22:29:58Z**

November 7, 2026 final readback passed. On main `6300d463d1b61ebe05b4505b97537884b4842894`, the installed Congress Explorer 0.6.2 wheel and hosted MCP both returned archive `5d24699ad9fa076e3e10c894a1cb3310ab35b12e8025adcca87feca7978080c1` for all four named research queries. Seven rows on each reader matched the retained release-row comparisons, including canonical IDs, references, null fields, coverage, and order. Five timezone-aware hearing fields matched by instant across local and UTC formatting. The four recipe tables, schema, and relevant logic matched the inputs for the retained 19-row paging, ambiguity, empty-window, and unavailable-collection checks. ct-6r1i conservation and ct-hnpc activity acceptance are recorded for this release.

The scoped acceptance criteria are complete. Close ct-nozw. [Final readback](../.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-nozw/final-readback-continuation-5d24699a.json). [Acceptance summary](../.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-nozw/final-acceptance-5d24699a.json).
