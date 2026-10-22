---
id: ct-gi01
status: closed
deps: []
links: [ct-8kl2, ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-aia9, ct-2yl5, ct-bwac, ct-a3le]
created: 2026-10-21T20:53:31Z
type: feature
priority: 2
assignee: mikewolfd
external-ref: ss-023x,ss-65bz,ss-6gwu
parent: ct-8kl2
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
