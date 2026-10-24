---
id: ct-gi01
status: open
deps: []
links: [ct-8kl2, ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-aia9, ct-2yl5, ct-bwac, ct-a3le, ct-0odd, ct-ec91, ct-3ttc, ct-84xa, ct-h23e, ct-f7p8, ct-98sm, ct-r6xw, ct-jnw5, ct-4g55, ct-xx7q, ct-s9p2]
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

## Design

1. Migrate the 9 weekly retention state modules (congress_meetings, house_events, senate_events, gpo_hearings, youtube_videos, captions, transcripts, rejected_pages) to incremental docspec-rs tables.
2. Model multi-source Committee Explorer entity resolution (committees, meetings, materials, witnesses, issues, sources) as incremental docspec-rs RefreshSpec AggregateTransform views using FirstValueBy and CollectDistinctWithProvenance (ss-023x), while keeping domain conflict dismissal (_review_old_label_conflict, 'unknown' access transitions, DataIssue emission) in committee_meeting / committee_explorer domain policy.
3. Materialize the 6 browser Parquet tables (committees, meetings, materials, witnesses, issues, sources) via chained RefreshSpec (ss-65bz) + ExportSpec (ss-6gwu), and retire assemble.py's 15.3 GB in-memory accumulator, the 20 GB swap file in publish-explorer.yml, and the legacy .json.gz sharded writer/reader (export.py:556-651, query.py:write_query_partitions, parquet.py:migrate, and apps/site/src/components/explorer/reader/data-source.ts:174-381).

## Acceptance Criteria

- Weekly source updates and Committee Explorer publication run incrementally on docspec-rs in bounded memory (<2 GB RSS) without full-corpus .json.gz/CSV re-parsing or the 20 GB swap file in publish-explorer.yml.
- Legacy .json.gz sharded Committee Explorer exports and the .json.data bucket reader in data-source.ts are removed.

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
