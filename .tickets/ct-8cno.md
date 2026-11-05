---
id: ct-8cno
status: open
deps: []
links: [ct-m104, ct-itcg, ct-mx3g]
created: 2026-11-03T01:00:02Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, rosters, spicy-regs, phase2]
---

# Make historical committee rosters available for Congresses 113–118

Researchers should be able to find who served on committees and subcommittees in earlier Congresses. The pinned SpicyRegs input and the published `e145d24c389e` roster each contain 2,973 seats, all in Congress 119. Every published seat resolves to a member and committee. The release already describes this coverage accurately.

## Root cause and next step

The current House and Senate sources describe the sitting Congress, and the SpicyRegs rollup requests that Congress. The archive preserves the Congress values it receives. Upstream `ss-ehci` owns selecting dated historical captures, verifying the source period and publishing the historical generation. The current Senate file does not state a Congress, so historical Senate seats need separate publisher-backed period evidence.

Wait for the accepted SpicyRegs generation, then pin it through the existing archive job. Reuse committee and member normalization, the seat key `(congress, system_code, bioguide_id)`, and party and rank handling. Preserve dated provenance, supplied leadership roles and explicit missing or unreadable source dispositions. If upstream retains multiple dated versions of a seat, establish which observation represents the published Congress roster. Congress 112 is outside the supported span.

## Acceptance Criteria

- Record the accepted upstream source evidence and generation, the native archive result, and the published release separately. The published `rosters.parquet` covers committees and subcommittees in Congresses 113–119 and preserves Chair, Ranking Member and Vice Chair where supplied.
- Verify zero duplicate seats and `missing_committee_keys = 0` and `missing_member_keys = 0`. Confirm the selected installed `committee_roster` recipe returns representative history for Congresses 116, 117 and 118.
- Run the existing `archive_schema --check`. Verify the schema, generated relationship documentation and reader results describe the populated Congresses and limits of `committee_assignments`, including unavailable history.

Evidence is in the November 5 release, `model/jobs/spicy-regs/spicy-regs.json`, `model/sql/entity-rosters.sql` and the upstream `ss-ehci` ticket. [Release notes](../docs/releases/2026-11-05-e145d24c389e.md)

[November 5 root-cause analysis and source evidence](../docs/plans/production-mvp-root-causes-round2-20261105.md).

## Notes

**2026-11-03T12:48:59Z**

SQL, schema, and invariants implemented and verified on r3-mcp / release-train (4d583687): (congress, system_code, bioguide_id) deduplication, hs* -> hl*/ht* normalization including parent_system_code in entity-committees.sql, Congress-overlapping term party attribution and collision-free rank offsets in entity-rosters.sql, and missing_member_keys == 0 check in archive_model.py. Remaining step to close: publish and pin upstream spicy-regs committee-rosters generation containing 113th-118th Congress assignments in model/jobs/publish-model.json.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.

**2026-11-04T02:21:36Z**

Reopened 2026-11-03 (post-release acceptance test): rosters.parquet in live e4538f00 has congress 119 only (2,973 rows). The archive-side SQL landed (3a91ee98); 113-118 history is blocked upstream on spicy-stack ss-ehci (dated roster captures per Congress on spicy-regs main; the earlier branch prototype was retired by owner decision 2026-10-30).

**2026-11-04T15:07:16Z**

2026-11-04 accountability investigation: missing upstream history still blocks historical normalization. Live release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; checkout inspected separately at 730a2d8e0c55880fc058d13cc74d265fc315f41f. This is ticket-only follow-up to chaos-personas-20261104; no repair, tests, source regeneration or publication was performed. Fresh runtime schema is retained in .cache/archive-release/chaos-personas-20261104/ticket-accountability/runtime-check.json.

For e4538f00 the independent roster count remains 2,973 rows, Congress 119 only; the fresh runtime metadata agrees. The normalized hearing-count query has matching rosters for 148 of 188 committee associations with hearings in Congress 119, and cannot normalize Congresses 112–118. Evidence: .cache/archive-release/chaos-personas-20261104/independent-table-audit.json; accountability/calls.jsonl call 55; investigation-accountability/cases.json P3Q1. The 148/188 figure is committee associations in that query population, not proof those unmatched committees should all have seats.

Current model/sql/entity-rosters.sql:27-40 reads, deduplicates and retains supplied Congress values from spicy_committee_assignments; it cannot synthesize history absent from its pinned generation. Verified upstream dependency remains open /Users/mikewolfd/Work/spicy-stack/.tickets/ss-ehci.md: dated source-catalog-selected roster captures on main's roster implementation, explicit read failures, and built/published per-Congress history. Its owner decision retires the old branch prototype. Treat that current upstream plan as authoritative rather than reviving the superseded branch/YAML approach from this ticket's older Design prose.

Smallest remaining acceptance: finish and publish ss-ehci's dated history, pin that generation, retain the existing key/reference invariants, qualify/publish archive output, then demonstrate historical committee_roster queries against the installed selected release. The persona's 112th-Congress request lies outside the stated 113th–119th schema-support span and needs a separate source/coverage decision; this ticket does not silently promise it. Correcting ct-mx3g's wording is independent from acquiring history. Preserve status open; no data or pin changes were made.

**2026-11-04T15:23:03Z**

Coordinated producer plan frozen 2026-11-04: docs/plans/congress-explorer-root-cause-remediation-20261104.md. This addendum refines remaining work without rewriting prior evidence. Live evidence remains release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; source inspected at 730a2d8e0c55880fc058d13cc74d265fc315f41f. Planning/ticket update only: no implementation, tests, prepare, acquisition, data changes or publication.

Owner split: open spicy-stack ss-ehci supplies dated source-catalog-selected roster history on main; archive entity-rosters.sql:27-40 retains supplied Congress values, deduplicates and exports them. The retired branch prototype is not an implementation base. Preserve literal source Congress, dated provenance, per-Congress committee/member multiplicity and explicit failed-read/missing-history outcomes; do not infer Congress from URLs or fabricate the persona's unsupported 112th data.

Hard dependency: an accepted, published upstream history generation before changing the archive input pin and claiming 113th-118th roster availability. Keep current 119-only data/status explicit while that is unresolved. Archive fixture/key/reference checks and wording acceptance can proceed in parallel; ct-mx3g truthful metadata does not wait for acquisition. Add only representative historical/current and absent-history cases to maintained tests; reference-key parity and no duplicate committee/member seat assertions remain required.

Once the upstream generation exists, record its exact pin/delta and affected archive dependency closure, reuse unchanged records/completions, and measure expected memory/scratch/work before a heavy run under the existing watchdog. No broad raw scan, backfill or performance claim is authorized by this plan. Closure requires source-history evidence, native roster invariant/parity, qualified publication and actual committee_roster queries against the installed selected release, not schema support or local SQL alone.

**2026-11-05T21:34:21Z**

Independent reviewer `/root/coverage_acceptance` verified the retained `e145d24c389e` roster and recipe. All 2,973 seats belong to Congress 119, with zero duplicate seat keys and zero missing member or committee references. The `hsif00` recipe returned 54 current seats and zero rows for Congresses 113–118, consistent with the published availability note. The focused `archive_schema --check` passed. [Independent acceptance](../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/acceptance/source-coverage/independent-acceptance.md) · [Schema check](../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/source-coverage/archive-schema-check.log)

Historical delivery still depends on an accepted dated upstream ss-ehci generation. Once available, pin and qualify it, verify key and reference invariants and leadership roles, then publish and run representative historical roster queries against the installed selected release. The archived source-coverage handoff records the local verification boundary. [Integration handoff](../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/acceptance/source-coverage/HANDOFF.md)
