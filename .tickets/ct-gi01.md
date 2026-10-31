---
id: ct-gi01
status: open
deps: []
links: [ct-8kl2, ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-aia9, ct-2yl5, ct-bwac, ct-a3le, ct-0odd, ct-ec91, ct-3ttc, ct-84xa, ct-h23e, ct-f7p8, ct-98sm, ct-r6xw, ct-jnw5, ct-4g55, ct-xx7q, ct-s9p2, ct-w8dc, ct-93zs, ct-m104, ct-t915, ct-5kto, ct-m94a]
created: 2026-10-21T20:53:31Z
type: feature
priority: 2
assignee: mikewolfd
external-ref: ss-023x,ss-65bz,ss-6gwu
parent: ct-7uit
tags: [committee_explorer, congress_api, docspec, parquet]
---
# Migrate committee_explorer (apps/committee_youtube) and the 9 weekly .json.gz/CSV retention modules onto incremental docspec-rs tables & ExportPins (eliminating the 15.3 GB RAM / 20 GB swap CI bottleneck)

While news_lake and raw/catalog use docspec-rs, congress_api/retention still writes 9 weekly state modules as custom .json.gz and CSV snapshots (meetings.py, gpo.py, house.py, senate.py, tables.py, jsonl.py, captions.py, transcripts.py, rejected_pages.py), and apps/committee_youtube/src/committee_explorer loads 1,071,000 frozen Pydantic objects into Python RAM (peaking at 15.3 GB RSS and requiring a 20 GB Linux swap file in .github/workflows/publish-explorer.yml:76-83) on every run.

## Original design (superseded implementation approach)

1. Migrate the 9 weekly retention state modules (congress_meetings, house_events, senate_events, gpo_hearings, youtube_videos, captions, transcripts, rejected_pages) to incremental docspec-rs tables.
2. Model multi-source Committee Explorer entity resolution (committees, meetings, materials, witnesses, issues, sources) as incremental docspec-rs RefreshSpec AggregateTransform views using FirstValueBy and CollectDistinctWithProvenance (ss-023x), while keeping domain conflict dismissal (_review_old_label_conflict, 'unknown' access transitions, DataIssue emission) in committee_meeting / committee_explorer domain policy.
3. Materialize the 6 browser Parquet tables (committees, meetings, materials, witnesses, issues, sources) via chained RefreshSpec (ss-65bz) + ExportSpec (ss-6gwu), and retire assemble.py's 15.3 GB in-memory accumulator, the 20 GB swap file in publish-explorer.yml, and the legacy .json.gz sharded writer/reader (export.py:556-651, query.py:write_query_partitions, parquet.py:migrate, and apps/site/src/components/explorer/reader/data-source.ts:174-381).

## Current scope — 2026-10-30 reconciliation

Reopened at the user's request. Complete the move to the native model and shared
publication; the old weekly-mirror/RefreshSpec design above is historical, not an
instruction to restore duplicate tables. The current scope and field inventory
are in docs/plans/phase-2-annex-20261028.md §4.6. Preserve the earlier fixes and measurements.

Own the inventory and native mappings for all retained Explorer inputs, including
committee channels, collected videos, recording-match decisions, hearing
completeness, retained committee amendment/vote records, omitted meeting fields,
and the detailed SpicyRegs records needed by existing research uses. Record exact
snapshots, row meanings, identities, provenance, conflicts and missingness. Use
typed shared release data, stable evidence references, or explicitly described
pinned upstream relations. Any deferral of existing user-facing data needs an
explicit scope decision; an unimplemented field remains an acceptance gap.

Production evidence still shows publish-explorer.yml selecting legacy JSON/CSV
inputs and producing a separate publication. Commit 909b9c72's optional lake
arguments and local tests are useful implementation, not production cut-over.
Reuse DocSpec's native jobs/table/export operations. Missing generic engine
capabilities belong under ss-oxg1; no engine gap is established by this audit.

## Acceptance Criteria

- Complete the field inventory and preservation mapping in docs/plans/phase-2-annex-20261028.md §4.6; no populated field or unresolved record disappears without a recorded disposition and evidence.
- Preserve facts or decisions held only in derived files before retiring their readers; distinguish reported source facts from derived matching decisions.
- Version typed release schemas/keys/provenance with the producer and shared release registry. Include channel/video research, completeness/issues, retained committee records and useful meeting attributes; identify summaries separately from pinned upstream detail.
- The actual production job configuration selects pinned lake meeting/appearance records and SpicyRegs generations and runs native model/export jobs. Optional CLI flags or a native re-export of legacy Python assembly do not satisfy this criterion.
- A frozen-input comparison accounts for old/new records, missingness, conflicts and exclusions by reason. Record runtime, peak memory and objects/bytes read and written; meet the existing bounded-memory target (<2 GB RSS) without full-corpus legacy JSON/CSV assembly or a 20 GB swap file, or record an explicit approved revision to that target before closure.
- The shared native release supports ct-t915's site and ct-m104's MCP checks. Record local, integrated and live evidence separately; ct-5kto owns retirement after live acceptance.

## Audit 2026-10-24

- Verdict: PARTIAL (batch kl2a1aa).
- Grades: proposal 83 → 83, work 66 → 66.
- Problem: The explorer still assembles in Python and re-parses full `.json.gz`/CSV inputs, and removing the old `migrate` import broke Pages deploys for about 2.5 days.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:39
- Status: Reopened: revisit under engine-first rule. Unmet: AC1; the explorer still assembles in Python, writes Parquet itself with docspec only as an optional re-export (`export.py:944-960`), and re-parses full `.json.gz`/CSV inputs. The weekly-mirror part goes with WS10 (ct-r6xw). No plan workstream owns the explorer; linked to the epic ct-98sm for the owner to place.
- See docs/reviews/2026-10-24-ticket-audit/README.md

## Notes

**2026-10-24T18:47:54Z**

Moved under WS7 (ct-7uit). Engine-first: build the Committee Explorer tables with the engine's export, and delete the temporary docspec re-export that is thrown away (export.py:957-984). Folds in the explorer issues from ct-jnw5 (first witness only, saved_copy_sha256 at 0%, lost page indexes), ct-4g55 (export() grew to 687 lines), ct-xx7q (citations re-pointed to records lacking the quoted value) and ct-s9p2 (key source_record ids on content, not the whole-file input_id, so dedup isn't needed forever).

**2026-10-30T17:33:44Z**

Completed Phase 2 F3 in 909b9c72: added apps/committee_youtube/src/committee_explorer/lake_inputs.py and wired --meeting-records, --appearance-records, and --spicy-regs into ExportOptions, export(), reuse.py:request_key(), and CLI main() in apps/committee_youtube/src/committee_explorer/export.py so Committee Explorer reads meeting_records and appearance_records from the lake and committees/members/rosters from spicy-regs (simplification-plan-20261024.md §6.6 item 3, phase-2-annex-20261028.md §4.1). Verified with uv run pytest -q packages/congress_api/tests/test_explorer_export.py apps/committee_youtube/tests/ (98 passed).

**2026-10-30T20:37:05Z**

Reopened and reconciled at the user’s request on 2026-10-30. Current scope and acceptance above supersede the earlier closure where it claimed the remaining Explorer migration was complete. Canonical coverage and order: docs/plans/phase-2-annex-20261028.md §4.6. No implementation, live publication or deletion was performed by this reconciliation.
