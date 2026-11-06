# Model and consumer inventory for DDK replacement

The required scope is the entire congressional-tech workspace. This inventory names 54 capabilities; their full replacement status remains unverified. The user's later greenfield decision updates every reader together and removes old consumer-format compatibility from acceptance. Source history, multiple versions, retired-key notices and new-stack recovery remain required. Existing baseline tests and focused replacement tests establish only their stated scope. DDK owns reusable definitions, design checks, catalogs and evidence composition; DocSpec owns native execution, durable phases, protection, reconciliation and managed selection. Maintained domain parsers and user journeys may remain.

Frozen baseline `a06eb64bf3caa4a44e12a89bdd08939323de3092`, branch `codex/ddk-congress-replacement-20261106`. Read-only current main was `83238d6a`; committed diff from baseline named only .tickets/ct-m104.md and ct-m704.md. Untracked .tmp/ and docs/measurements/congress-mcp-persona-chaos-20261105.md were untouched. No inventoried source drift observed. This is point-in-time evidence.

The initial inventory observed implementationReady=false. The parent release record was re-read after review: `/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/release-status.json` updatedAt `2026-11-06T10:35:53.437087+00:00` then had implementationReady=true and releaseState `local-release-complete; local-replacement-implementation-authorized; publication-destination-pending`; replacementProductionCutoverAuthorized=false. These are historical observations; the parent's current status records govern activation. Focused declaration, consumer and transport checks do not establish full replacement or native candidate qualification.

## Current greenfield reader decisions

The authored archive definitions now contain 23 datasets, 257 physical fields (the frozen 254 plus three current capture-eligibility fields), 70 relationships and 16 recipes. MCP discovery and the browser read the admitted public `catalog.ddk.json`, its exact report and lock companions directly. They have no `schema.json` fallback or reverse schema converter. The field/grain census below remains a frozen baseline transcription unless explicitly updated here; baseline registry paths identify evidence, not the new definition owner. `model/ddk/archive.odcs.json:1` and `model/ddk/project.ddk.json:1` hold the current declarations. Native producer integration and accepted exact-candidate evidence remain separate, incomplete work.

`detail.document_date_status` is physically present and nullable; document summaries retain null instead of omitting the field. A present detail table without it refuses (`apps/explorer_mcp/src/congressional_explorer_mcp/reader.py:55`; `apps/site/src/components/explorer/reader/archive.ts:166`). Retired-key lookup requires the present nullable `retired_links.address_versions` field, preserves successor/removal history and handles null or empty lists without inventing editions. The whole retired-links table may be absent (`reader.py:170`; `archive.ts:283`). These are narrow checks at actual use, not another schema validator.

Recording associations come only from required `recording_matches.meeting_links`. Empty means no supported links; an absent optional table is missing; a present unreadable or obsolete-shaped table is unavailable. There is no event/package fallback. Current package-context links still expose the exact original package evidence without claiming full-event footage (`model/sql/entity-recording-matches.sql:56`; `apps/site/src/components/explorer/reader/archive-entities.ts:339`). Transcript sources retain their explicit labels; null, absent or blank source displays “Source not stated,” never an inferred printed hearing. Unknown nonempty source strings remain visible (`archive-entities.ts:66`; `apps/site/src/components/explorer/archive/HearingDetail.tsx:241`).

## Retained evidence and source/release drift

Retained published release `e145d24c389e43e05a0bcb3f71cd1f75ee919a066dfa810f0ba39a16283d4a99` has 23 Parquet tables and three controls (26 assets). The retained manifest is metadata, not a fresh network/payload audit: `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1`. Retained acceptance `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/final-acceptance/acceptance.json:1` records six suites, 73 explained comparison groups, no missing retired links, 182 pre-publication MCP/33 browser assertions. Handoff separately records 180 live MCP/57 deployed-browser assertions; stages are not interchangeable. Offline qualification `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/qualification-7f9ebddd2cb6/combined-results.json:1` records 11,497 passes, 37 skips, three expected malformed-House-XML failures at older source. None was rerun or proves replacement.

Current schema has 70 relationships/16 recipes; retained e145 has 69/16. Comparing only small JSON schemas (`/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/candidate-streaming-repair/model-output/schema.json:1`) found current additions absent in retained release:

- `detail.parquet`: added ['description', 'main_content', 'modified_on', 'page_metadata', 'published_on', 'publisher_labels', 'selected_text']; changed declarations [].
- `meetings.parquet`: added ['chamber_basis', 'document_references']; changed declarations [].
- `nominations.parquet`: added ['committee_activities']; changed declarations [].
- `recording_matches.parquet`: added ['meeting_links', 'subject_id']; changed declarations [].
- `meeting_coverage.parquet`: added []; changed declarations ['reason'].
- Added relationship: ['match_meeting_associations'].

Authentic acceptance for new page metadata/text, meeting source precision, nomination activities and event/package recording links remains required. Current code support and retained release data are separate obligations.

## Exact manifest census

Manifest identity binds ordered names/digests/sizes/rows and schema_version=1. Current readers require list/detail/links/urls/sources/recoveries/url_state plus capture_scope.json and catalog.ddk.json/catalog.report.json/catalog.lock.json. Every catalog companion must belong to the same immutable manifest. schema.json is refused. Only detail/sources support contiguous absolute half-open shards. Optional absent table is missing; present zero-row table is available empty; missing required asset refuses (`apps/explorer_mcp/src/congressional_explorer_mcp/release.py:112`; `apps/site/src/components/explorer/reader/archive.ts:104`). The following table inventories the retained pre-migration release, including its historical schema.json; it is not a current required-control list.

| Asset | Rows | Bytes | Retained metadata |
| --- | ---: | ---: | --- |
| `list.parquet` | 356,735 | 6,918,257 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `detail.parquet` | 356,735 | 26,880,700 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `links.parquet` | 441,163 | 4,060,489 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `urls.parquet` | 611,729 | 5,593,084 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `sources.parquet` | 580,383 | 8,501,483 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `recoveries.parquet` | 12,618 | 624,615 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `meetings.parquet` | 18,687 | 1,908,156 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `witnesses.parquet` | 172,964 | 8,672,026 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `witness_key_map.parquet` | 154,089 | 2,927,522 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `recordings.parquet` | 12,289 | 244,606 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `committees.parquet` | 818 | 33,275 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `members.parquet` | 12,770 | 460,548 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `rosters.parquet` | 2,973 | 9,840 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `bills.parquet` | 52,279 | 4,431,397 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `nominations.parquet` | 748 | 49,686 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `videos.parquet` | 67,391 | 8,636,785 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `channels.parquet` | 119 | 11,804 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `recording_matches.parquet` | 32,088 | 2,173,750 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `committee_records.parquet` | 19,985 | 1,546,960 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `meeting_coverage.parquet` | 93,435 | 125,832 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `url_state.parquet` | 1,198,646 | 17,719,329 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `url_variants.parquet` | 0 | 380 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `retired_links.parquet` | 450 | 16,530 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `schema.json` | 0 | 95,904 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `capture_scope.json` | 0 | 4,990 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |
| `capture_profile.json` | 0 | 6,811 | `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json:1` |

Full SHA-256 for each asset is retained in that manifest. Before reuse, verify accepted custody. No payload scan/re-hash was needed for this census.

## Lake table/field/type census

Eight schemas and eight exact native-table pins in model/jobs/publish-model.json, including playlist_records at line 96. Preserve schema IDs, identifier field IDs, field IDs and nested element IDs. ! means required; ? optional. Full nested fields follow rather than generic JSON.

### `appearance-records.schema.json`

`model/lake/appearance-records.schema.json:1`; schema-id=0; identifier-field-ids=[1, 5, 2].

- `record_sha!`: `fixed[32]`, id=1.
- `parser_version!`: `string`, id=2.
- `status!`: `string`, id=3.
- `error_type?`: `string`, id=4.
- `source!`: `string`, id=5.
- `event_id?`: `long`, id=6.
- `package_id?`: `string`, id=7.
- `declared_base?`: `string`, id=8.
- `collection_state?`: `string`, id=9.
- `appearances!`: list<struct>, id=10, element-id=11, element-required=True.
- `appearances[].source_locator!`: `string`, id=12.
- `appearances[].name_key?`: `string`, id=13.
- `appearances[].name?`: `string`, id=14.
- `appearances[].honorific?`: `string`, id=15.
- `appearances[].given?`: `string`, id=16.
- `appearances[].middle?`: `string`, id=17.
- `appearances[].family?`: `string`, id=18.
- `appearances[].suffix?`: `string`, id=19.
- `appearances[].position?`: `string`, id=20.
- `appearances[].organization?`: `string`, id=21.
- `appearances[].on_behalf_of?`: `string`, id=22.
- `appearances[].location?`: `string`, id=23.
- `appearances[].panel?`: `string`, id=24.
- `appearances[].panel_order?`: `int`, id=25.
- `appearances[].display_order?`: `int`, id=26.
- `appearances[].witness_type?`: `string`, id=27.
- `appearances[].testified?`: `boolean`, id=28.
- `appearances[].bioguide_id?`: `string`, id=29.
- `appearances[].document_links!`: list<string>, id=30, element-id=31, element-required=True.
- `held_dates?`: list<string>, id=32, element-id=33, element-required=True.
- `title?`: `string`, id=34.
- `created?`: `string`, id=35.

### `captures.schema.json`

`model/lake/captures.schema.json:1`; schema-id=0; identifier-field-ids=[1, 2, 3].

- `receipt_key!`: `string`, id=1.
- `receipt_line!`: `int`, id=2.
- `capture_index!`: `int`, id=3.
- `run_id!`: `string`, id=4.
- `mode!`: `string`, id=5.
- `outcome?`: `string`, id=6.
- `family!`: `string`, id=7.
- `requested_url?`: `string`, id=8.
- `url?`: `string`, id=9.
- `context_url?`: `string`, id=14.
- `member_path?`: `string`, id=15.
- `original_path?`: `string`, id=42.
- `h_content_disposition?`: `string`, id=17.
- `attempt?`: `int`, id=38.
- `http_status?`: `int`, id=11.
- `complete?`: `boolean`, id=13.
- `fetch_http_status?`: `int`, id=39.
- `fetch_outcome?`: `string`, id=40.
- `retrieved_at?`: `timestamptz`, id=19.
- `sha256?`: `fixed[32]`, id=20.
- `bytes?`: `long`, id=21.
- `media_type?`: `string`, id=22.
- `fidelity?`: `string`, id=23.
- `sniffed_format?`: `string`, id=24.
- `sniff_version?`: `string`, id=25.
- `intact?`: `boolean`, id=26.
- `expansion?`: `string`, id=16.
- `stored_suffix?`: `string`, id=27.
- `stored_bytes?`: `long`, id=29.
- `stored_md5?`: `fixed[16]`, id=28.
- `recovery_category?`: `string`, id=30.
- `original_url?`: `string`, id=31.
- `recovered_url?`: `string`, id=32.
- `match_basis?`: `string`, id=33.
- `evidence_sha256?`: `fixed[32]`, id=34.
- `imported_at?`: `timestamptz`, id=35.
- `writer_job?`: `string`, id=36.
- `writer_commit?`: `string`, id=37.
- `mapping_version?`: `string`, id=41.

### `committee-records.schema.json`

`model/lake/committee-records.schema.json:1`; schema-id=0; identifier-field-ids=[1, 5, 2].

- `record_sha!`: `fixed[32]`, id=1.
- `parser_version!`: `string`, id=2.
- `status!`: `string`, id=3.
- `error_type?`: `string`, id=4.
- `source!`: `string`, id=5.
- `records!`: list<struct>, id=6, element-id=7, element-required=True.
- `records[].ordinal!`: `int`, id=8.
- `records[].kind!`: `string`, id=9.
- `records[].bill?`: `string`, id=10.
- `records[].number?`: `string`, id=11.
- `records[].sponsor_bioguide?`: `string`, id=12.
- `records[].amendment_type?`: `string`, id=13.
- `records[].enbloc?`: `string`, id=14.
- `records[].description?`: `string`, id=15.
- `records[].url?`: `string`, id=16.
- `event_id?`: `string`, id=17.
- `updated?`: `string`, id=18.

### `filename-readings.schema.json`

`model/lake/filename-readings.schema.json:1`; schema-id=0; identifier-field-ids=[1, 2, 3].

- `filename!`: `string`, id=1.
- `source_url!`: `string`, id=2.
- `catalog_version!`: `string`, id=3.
- `status!`: `string`, id=4.
- `error_type?`: `string`, id=5.
- `valid!`: `boolean`, id=6.
- `document_kind!`: list<string>, id=7, element-id=19, element-required=True.
- `document_family!`: list<string>, id=8, element-id=20, element-required=True.
- `committee_code!`: list<string>, id=9, element-id=21, element-required=True.
- `congress?`: `int`, id=10.
- `date_token?`: `string`, id=11.
- `measure_type?`: `string`, id=12.
- `measure_number?`: `string`, id=13.
- `filename_date?`: `date`, id=14.
- `measure_keys!`: list<string>, id=15, element-id=22, element-required=True.
- `bioguide_ids!`: list<string>, id=16, element-id=23, element-required=True.
- `package_id?`: `string`, id=17.
- `fields!`: list<struct>, id=18, element-id=24, element-required=True.
- `fields[].field!`: `string`, id=25.
- `fields[].value!`: `string`, id=26.

### `meeting-records.schema.json`

`model/lake/meeting-records.schema.json:1`; schema-id=0; identifier-field-ids=[1, 5, 2].

- `record_sha!`: `fixed[32]`, id=1.
- `parser_version!`: `string`, id=2.
- `status!`: `string`, id=3.
- `error_type?`: `string`, id=4.
- `source!`: `string`, id=5.
- `meetings!`: list<struct>, id=6, element-id=7, element-required=True.
- `meetings[].event_id!`: `string`, id=8.
- `meetings[].chamber?`: `string`, id=9.
- `meetings[].congress?`: `int`, id=10.
- `meetings[].session?`: `int`, id=11.
- `meetings[].updated?`: `string`, id=12.
- `meetings[].title?`: `string`, id=13.
- `meetings[].meeting_date?`: `string`, id=14.
- `meetings[].meeting_type?`: `string`, id=15.
- `meetings[].status?`: `string`, id=16.
- `meetings[].sittings!`: list<struct>, id=17, element-id=18, element-required=True.
- `meetings[].sittings[].start?`: `string`, id=19.
- `meetings[].sittings[].end?`: `string`, id=20.
- `meetings[].sittings[].room?`: `string`, id=21.
- `meetings[].sittings[].building?`: `string`, id=22.
- `meetings[].sittings[].address?`: `string`, id=23.
- `meetings[].committees!`: list<struct>, id=24, element-id=25, element-required=True.
- `meetings[].committees[].system_code?`: `string`, id=26.
- `meetings[].committees[].name?`: `string`, id=27.
- `meetings[].committees[].chamber?`: `string`, id=28.
- `meetings[].committees[].role?`: `string`, id=29.
- `meetings[].subject_keys!`: list<string>, id=30, element-id=31, element-required=True.
- `meetings[].transcript_jackets!`: list<int>, id=32, element-id=33, element-required=True.
- `meetings[].videos!`: list<struct>, id=34, element-id=35, element-required=True.
- `meetings[].videos[].video_key?`: `string`, id=36.
- `meetings[].videos[].url?`: `string`, id=37.
- `meetings[].videos[].title?`: `string`, id=38.
- `meetings[].document_urls?`: list<string>, id=39, element-id=40, element-required=True.
- `meetings[].collection_states?`: struct, id=41.
- `meetings[].collection_states.sittings?`: `string`, id=42.
- `meetings[].collection_states.committees?`: `string`, id=43.
- `meetings[].collection_states.subject_keys?`: `string`, id=44.
- `meetings[].collection_states.transcript_jackets?`: `string`, id=45.
- `meetings[].collection_states.videos?`: `string`, id=46.
- `meetings[].collection_states.document_urls?`: `string`, id=47.
- `meetings[].access?`: `string`, id=48.
- `meetings[].access_basis?`: `string`, id=49.
- `meetings[].not_held?`: `boolean`, id=50.
- `meetings[].title_key?`: `string`, id=51.
- `meetings[].reschedule_candidate?`: `boolean`, id=52.
- `meetings[].document_references?`: list<struct>, id=53, element-id=54, element-required=True.
- `meetings[].document_references[].collection!`: `string`, id=55.
- `meetings[].document_references[].ordinal!`: `int`, id=56.
- `meetings[].document_references[].url!`: `string`, id=57.
- `meetings[].document_references[].role?`: `string`, id=58.
- `meetings[].document_references[].format?`: `string`, id=59.
- `meetings[].document_references[].description?`: `string`, id=60.
- `meetings[].document_references[].name?`: `string`, id=61.

### `playlist-records.schema.json`

`model/lake/playlist-records.schema.json:1`; schema-id=0; identifier-field-ids=[1, 5, 2].

- `record_sha!`: `fixed[32]`, id=1.
- `parser_version!`: `string`, id=2.
- `status!`: `string`, id=3.
- `error_type?`: `string`, id=4.
- `source!`: `string`, id=5.
- `segments!`: list<string>, id=6, element-id=7, element-required=True.
- `playlists!`: list<string>, id=8, element-id=9, element-required=True.

### `readings.schema.json`

`model/lake/readings.schema.json:1`; schema-id=0; identifier-field-ids=[1, 2, 3].

- `body_sha!`: `fixed[32]`, id=1.
- `parser!`: `string`, id=2.
- `parser_version!`: `string`, id=3.
- `status!`: `string`, id=4.
- `error_type?`: `string`, id=5.
- `format?`: `string`, id=6.
- `xml_root?`: `string`, id=7.
- `title?`: `string`, id=8.
- `heading?`: `string`, id=9.
- `text_head?`: `string`, id=10.
- `content_date?`: `date`, id=11.
- `base_href?`: `string`, id=12.
- `text_bytes?`: `int`, id=13.
- `link_count?`: `int`, id=14.
- `link_text_bytes?`: `int`, id=15.
- `intact?`: `boolean`, id=16.
- `named_meetings!`: list<long>, id=17, element-id=101, element-required=True.
- `links!`: list<struct>, id=18, element-id=102, element-required=True.
- `links[].href!`: `string`, id=110.
- `links[].text!`: `string`, id=111.
- `links[].tag!`: `string`, id=112.
- `links[].basis!`: `string`, id=113.
- `links[].group_path?`: `string`, id=114.
- `links[].doc_type?`: `string`, id=115.
- `links[].add_date?`: `string`, id=116.
- `links[].publish_date?`: `string`, id=117.
- `links[].remove_date?`: `string`, id=118.
- `fingerprint?`: `fixed[32]`, id=19.
- `fields!`: list<struct>, id=20, element-id=103, element-required=True.
- `fields[].field!`: `string`, id=120.
- `fields[].value!`: `string`, id=121.

### `video-records.schema.json`

`model/lake/video-records.schema.json:1`; schema-id=0; identifier-field-ids=[1, 5, 2].

- `record_sha!`: `fixed[32]`, id=1.
- `parser_version!`: `string`, id=2.
- `status!`: `string`, id=3.
- `error_type?`: `string`, id=4.
- `source!`: `string`, id=5.
- `channels!`: list<struct>, id=6, element-id=7, element-required=True.
- `channels[].handle!`: `string`, id=8.
- `channels[].channel_id?`: `string`, id=9.
- `channels[].title?`: `string`, id=10.
- `channels[].custom_url?`: `string`, id=11.
- `channels[].uploads_scan_complete?`: `boolean`, id=12.
- `videos!`: list<struct>, id=13, element-id=14, element-required=True.
- `videos[].handle!`: `string`, id=15.
- `videos[].video_id!`: `string`, id=16.
- `videos[].channel_id?`: `string`, id=17.
- `videos[].channel_title?`: `string`, id=18.
- `videos[].title?`: `string`, id=19.
- `videos[].description?`: `string`, id=20.
- `videos[].published_at?`: `string`, id=21.
- `videos[].video_published_at?`: `string`, id=22.
- `videos[].duration_seconds?`: `int`, id=23.
- `videos[].available?`: `boolean`, id=24.
- `videos[].has_caption?`: `boolean`, id=25.
- `videos[].details_checked_at?`: `string`, id=26.
- `videos[].stated_event_ids!`: list<long>, id=27, element-id=28, element-required=True.

Historical readings may contain several versions per body/parser. archive_model.prepare_model_inputs installs compatible_versions.selected_readings_steps before joins; record tables select exact source/version (`model/sql/selected-records.sql:3`). Ranking/merge (`meeting-records-ranked.sql:49`, `meeting-records-merged.sql:15`) distinguishes same-update omission from explicit empty/unrecognized and genuinely later omission. Failed parsing must not become valid empty; three expected malformed XML failures remain baseline gap C40.

## Frozen baseline public table/field/type/grain census

dict is dictionary-encoded string; fixed[8] public key; fixed[32] SHA-256 bytes. Preserve native int/date/timestamp/null/list/struct semantics through Arrow, Parquet, DuckDB, worker structured clone and JSON. list_row is virtual physical position continued across shards, valid only inside one release. detail.link_key is public document identity; links can alias many keys to one row. Bytes, editions, alternate formats, source occurrences, recoveries and publications remain distinct.

### `list`

One document edition in this release. Identity `{"fields":["list_row"],"scope":"release","validation":"shared ordered native export","kind":"row_position","note":"list_row is virtual: zero-based physical row position, continued across manifest shard row ranges. Never reuse it across releases."}`. `model/registries/release-schema.json:5`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `filename` | `string` | no |
| `title` | `string` | yes |
| `document_kind` | `list<dict>` | no |
| `document_family` | `list<dict>` | no |
| `committee_keys` | `list<dict>` | no |
| `chambers` | `list<dict>` | no |
| `congress` | `int16` | yes |
| `format` | `dict` | no |
| `document_date` | `date32` | yes |
| `first_captured` | `date32` | yes |
| `date_kind` | `dict` | no |
| `saved_kind` | `dict` | no |
| `hidden` | `boolean` | no |
| `meeting_keys` | `list<dict>` | no |
| `measure_keys` | `list<dict>` | no |
| `bioguide_ids` | `list<dict>` | no |
| `witness_keys` | `list<dict>` | no |
| `version_keys` | `list<dict>` | no |

Declared limits: Date bounds span accepted document dates only and Congress bounds skip suspect-dated documents; document_dates counts accepted, suspect and undated documents. Bounds are observed values, not evidence of complete coverage

### `detail`

One document edition, in exactly the same order as list. Identity `{"fields":["link_key"],"scope":"release; a recovery-only document's key can move in a later release only as the data model section 8.2 states","validation":"native publication key checks","kind":"primary_key","note":"list_row stays virtual: zero-based physical row position, continued across manifest shard row ranges; never reuse it across releases. Older releases carry only the detail columns; their rows pair with list by list_row."}`. `model/registries/release-schema.json:146`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `link_key` | `fixed[8]` | no |
| `saved_body` | `fixed[32]` | no |
| `saved_suffix` | `dict` | no |
| `saved_media_type` | `dict` | no |
| `saved_bytes` | `int64` | no |
| `document_date_source` | `dict` | yes |
| `document_date_status` | `dict` | yes |
| `in_archive_since` | `date32` | yes |
| `removed_on` | `date32` | yes |
| `review_note` | `string` | yes |
| `review_decided_at` | `date32` | yes |
| `src_start` | `int32` | no |
| `src_len` | `int32` | no |
| `rec_start` | `int32` | no |
| `rec_len` | `int32` | no |
| `alternates` | `list<struct<format dict,body fixed[32],suffix dict,size int64>>` | no |
| `package_id` | `string` | yes |
| `facts` | `list<struct<field dict,value string>>` | no |
| `description` | `string` | yes |
| `published_on` | `date32` | yes |
| `modified_on` | `date32` | yes |
| `publisher_labels` | `list<dict>` | no |
| `page_metadata` | `list<struct<field dict,value string,format dict,path string,date date32,precision dict,resolved string,selected boolean,context_url string>>` | no |
| `main_content` | `struct<outcome dict,selector string,text_sha256 string,text_bytes int32,snippet string,reader_version string,reading_status string,reason string,facts_limited boolean,text_available boolean,decision_id string,evidence_limited boolean>` | yes |
| `selected_text` | `string` | yes |
| `filename` | `string` | no |
| `title` | `string` | yes |
| `document_kind` | `list<dict>` | no |
| `document_family` | `list<dict>` | no |
| `committee_keys` | `list<dict>` | no |
| `chambers` | `list<dict>` | no |
| `congress` | `int16` | yes |
| `format` | `dict` | no |
| `document_date` | `date32` | yes |
| `first_captured` | `date32` | yes |
| `date_kind` | `dict` | no |
| `saved_kind` | `dict` | no |
| `hidden` | `boolean` | no |
| `meeting_keys` | `list<dict>` | no |
| `measure_keys` | `list<dict>` | no |
| `bioguide_ids` | `list<dict>` | no |
| `witness_keys` | `list<dict>` | no |
| `version_keys` | `list<dict>` | no |

Declared limits: Date bounds span accepted document dates only and Congress bounds skip suspect-dated documents; document_dates counts accepted, suspect and undated documents. Bounds are observed values, not evidence of complete coverage

### `links`

One stable link key mapped to one release-local document row. Identity `{"fields":["link_key"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:450`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `link_key` | `fixed[8]` | no |
| `list_row` | `int32` | no |

### `retired_links`

One retired link key with its successor or a removal notice. Identity `{"fields":["link_key"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:482`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `link_key` | `fixed[8]` | no |
| `successor_key` | `fixed[8]` | yes |
| `last_release_id` | `string` | no |
| `last_filename` | `string` | yes |
| `address_versions` | `list<fixed[8]>` | yes |

### `urls`

One lookup key and document row pair; an address can identify several editions. Identity `{"fields":["lookup_key","list_row"],"scope":"release","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:533`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `lookup_key` | `fixed[8]` | no |
| `list_row` | `int32` | no |

### `sources`

One source address/context occurrence within a document. Identity `{"fields":["list_row","ordinal"],"scope":"release","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:566`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `list_row` | `int32` | no |
| `ordinal` | `int32` | no |
| `url` | `string` | no |
| `member_path` | `string` | yes |
| `is_saved` | `boolean` | no |
| `first_seen` | `date32` | yes |
| `listed_on` | `string` | yes |
| `link_text` | `string` | yes |
| `doc_type` | `string` | yes |
| `posted` | `date32` | yes |

### `recoveries`

One recovered file occurrence within a document. Identity `{"fields":["list_row","ordinal"],"scope":"release","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:648`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `list_row` | `int32` | no |
| `ordinal` | `int32` | no |
| `kind` | `dict` | no |
| `body` | `fixed[32]` | no |
| `suffix` | `dict` | no |
| `bytes` | `int64` | no |
| `imported_at` | `date32` | yes |
| `recovered_url` | `string` | no |
| `identity_note` | `string` | yes |

### `meetings`

One event, shared House/Senate event ID namespace. Identity `{"fields":["event_id"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:720`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `event_id` | `int64` | no |
| `chamber` | `dict` | yes |
| `chamber_basis` | `string` | no |
| `title` | `string` | yes |
| `meeting_date` | `date32` | yes |
| `meeting_type` | `dict` | yes |
| `session` | `int16` | yes |
| `status` | `dict` | yes |
| `sittings` | `list<struct<start timestamp,end timestamp,place string,room string,building string,address string>>` | no |
| `committees` | `list<struct<system_code dict,role dict>>` | no |
| `subject_keys` | `list<dict>` | no |
| `transcripts` | `list<struct<source dict,package_id string,list_row int32,formats list<string>,video_key string,language dict,production dict>>` | no |
| `videos` | `list<struct<name string,url string,video_key string>>` | no |
| `congress` | `int16` | yes |
| `congress_gov_updated` | `timestamp` | yes |
| `house_xml_updated` | `string` | yes |
| `congress_gov_meeting_type` | `dict` | yes |
| `access` | `dict` | yes |
| `access_basis` | `dict` | yes |
| `not_held` | `bool` | yes |
| `rescheduled_to` | `int64` | yes |
| `rescheduled_basis` | `dict` | yes |
| `document_references` | `list<struct<collection string, ordinal int32, url string, role string, format string, description string, name string>>` | yes |

### `witnesses`

One source-occurrence witness observation at a meeting, package, or page; not a deduplicated person. Identity `{"fields":["witness_key"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:888`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `witness_key` | `string` | no |
| `occasion` | `dict` | no |
| `source` | `dict` | no |
| `record_sha` | `fixed[32]` | no |
| `source_locator` | `string` | no |
| `context_key` | `string` | no |
| `event_id` | `int64` | yes |
| `package_id` | `string` | yes |
| `page_url` | `string` | yes |
| `name` | `string` | yes |
| `position` | `string` | yes |
| `organization` | `string` | yes |
| `on_behalf_of` | `string` | yes |
| `location` | `string` | yes |
| `panel` | `string` | yes |
| `panel_order` | `int16` | yes |
| `display_order` | `int16` | yes |
| `witness_type` | `dict` | yes |
| `testified` | `boolean` | yes |
| `bioguide_id` | `dict` | yes |
| `superseded_by` | `string` | yes |

### `witness_key_map`

One witness key this release no longer publishes, with its successor, its candidates, or neither. Identity `{"fields":["old_key"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1034`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `old_key` | `string` | no |
| `witness_key` | `string` | yes |
| `status` | `dict` | no |
| `basis` | `dict` | yes |
| `candidate_keys` | `list<string>` | no |
| `occasion` | `dict` | no |
| `source` | `dict` | no |

Declared limits: Derived from earlier bodies the lake still holds, not from earlier releases: a key published only from a body no longer held has no row

### `recordings`

One provider-prefixed recording. Identity `{"fields":["video_key"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1099`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `video_key` | `string` | no |
| `event_ids` | `list<int64>` | no |
| `tracks` | `list<struct<body fixed[32],suffix dict,format dict,language dict,production dict>>` | no |

### `committees`

One Congress.gov system code. Identity `{"fields":["system_code"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1137`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `system_code` | `string` | no |
| `name` | `string` | no |
| `chamber` | `dict` | no |
| `committee_type` | `dict` | yes |
| `parent_system_code` | `dict` | yes |
| `names` | `list<struct<name string,start date32,end date32>>` | no |
| `website` | `string` | yes |
| `is_current` | `boolean` | yes |

### `members`

One Bioguide member. Identity `{"fields":["bioguide_id"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1205`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `bioguide_id` | `string` | no |
| `name` | `string` | no |
| `terms` | `list<struct<chamber dict,state dict,district int16,party dict,start date32,end date32>>` | no |
| `cross_ids` | `struct<lis string,opensecrets string,govtrack string,icpsr string,wikidata string,fec list<string>>` | no |

### `rosters`

One member assignment to a committee or subcommittee in a Congress (keyed by congress, system_code, bioguide_id; only Congresses populated in the pinned upstream committee_assignments snapshot appear). Identity `{"fields":["congress","system_code","bioguide_id"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1250`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `congress` | `int16` | no |
| `system_code` | `dict` | no |
| `bioguide_id` | `dict` | no |
| `title` | `dict` | yes |
| `rank` | `int16` | yes |
| `party` | `dict` | yes |

Declared limits: Committee seats cover only the Congresses populated in the pinned upstream committee_assignments snapshot; congress_start and congress_end bound the published Congresses, and any Congress without roster rows, including every Congress when both are null, is unavailable, not zero seats

### `bills`

One bill referenced by documents, meetings, or committee activities, or a substantive/enacted bill (congress >= 113), plus 1-hop related bills of referenced bills; bounded by upstream retained data. Identity `{"fields":["bill_id"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1310`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `bill_id` | `string` | no |
| `title` | `string` | yes |
| `short_title` | `string` | yes |
| `sponsor_bioguide_id` | `dict` | yes |
| `introduced` | `date32` | yes |
| `latest_action_date` | `date32` | yes |
| `latest_action_text` | `string` | yes |
| `stage` | `dict` | yes |
| `policy_area` | `dict` | yes |
| `public_law_number` | `string` | yes |
| `cosponsor_count` | `int32` | yes |
| `related_bills` | `list<struct<bill_id string,title string,relationship_types list<dict>>>` | no |
| `committees` | `list<dict>` | no |
| `cbo_estimates` | `list<struct<publication_id string,date date32,description string>>` | no |
| `floor_votes` | `list<struct<vote_id string,basis dict,chamber dict,date date32,question string,result string,yea int16,nay int16>>` | no |
| `amendments` | `list<struct<amendment_id string,purpose string,sponsor_bioguide_id dict,latest_action_date date32,latest_action_text string>>` | no |
| `committee_activities` | `list<struct<system_code dict,activity dict,date date32>>` | no |

Declared limits: Amendments cover the 119th Congress only until spicy-regs backfills

### `nominations`

One nomination including its part when present; bounded by upstream retained data. Identity `{"fields":["nomination_id"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1439`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `nomination_id` | `string` | no |
| `description` | `string` | yes |
| `organization` | `string` | yes |
| `received` | `date32` | yes |
| `latest_action_date` | `date32` | yes |
| `latest_action_text` | `string` | yes |
| `committees` | `list<dict>` | no |
| `committee_activities` | `list<struct<system_code string, activities list<struct<name string, date string>>>>` | yes |
| `transcripts` | `list<string>` | no |
| `floor_votes` | `list<struct<vote_id string,date date32,question string,result string,yea int16,nay int16>>` | no |

Declared limits: Nominations cover the 119th Congress only until spicy-regs backfills

### `url_state`

One exact requested URL, including requests without a successful capture. Identity `{"fields":["requested_url"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1524`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `requested_url` | `string` | no |
| `attempts` | `int32` | no |
| `last_attempt` | `timestamp<microsecond,UTC>` | yes |
| `last_status` | `int16` | yes |
| `last_outcome` | `dict` | yes |
| `last_good_at` | `timestamp<microsecond,UTC>` | yes |
| `next_attempt_at` | `timestamp<microsecond,UTC>` | yes |

### `url_variants`

One canonical/variant URL pair used by capture policy. Identity `{"fields":["canonical_url","variant_url"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1586`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `canonical_url` | `string` | no |
| `variant_url` | `string` | no |

### `videos`

One upload a retained YouTube cache lists. Identity `{"fields":["video_key"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1619`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `video_key` | `string` | no |
| `handle` | `dict` | no |
| `channel_id` | `string` | yes |
| `system_code` | `dict` | yes |
| `title` | `string` | yes |
| `source_description` | `string` | yes |
| `published_at` | `timestamp` | yes |
| `video_published_at` | `timestamp` | yes |
| `duration_seconds` | `int32` | yes |
| `available` | `bool` | yes |
| `has_caption` | `bool` | yes |
| `details_checked_at` | `timestamp` | yes |
| `stated_event_ids` | `list<int64>` | no |
| `record_sha` | `fixed[32]` | no |

### `channels`

One curated channel handle. Identity `{"fields":["handle"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1723`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `handle` | `string` | no |
| `channel_id` | `string` | yes |
| `system_code` | `dict` | no |
| `committee_label` | `string` | yes |
| `role` | `dict` | no |
| `title` | `string` | yes |
| `custom_url` | `string` | yes |
| `uploads_scan_complete` | `bool` | yes |
| `mapping_basis` | `dict` | no |
| `record_sha` | `fixed[32]` | yes |

### `recording_matches`

One observation that a subject has, or lacks, a recording. Identity `{"fields":["match_id"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1801`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `match_id` | `string` | no |
| `subject_kind` | `dict` | no |
| `subject_id` | `string` | no |
| `event_id` | `int64` | yes |
| `package_id` | `string` | yes |
| `video_key` | `string` | yes |
| `url` | `string` | yes |
| `basis` | `dict` | no |
| `decision` | `dict` | yes |
| `score` | `int16` | yes |
| `recording_scope` | `dict` | yes |
| `status` | `dict` | no |
| `note` | `string` | yes |
| `source_ref` | `string` | yes |
| `meeting_links` | `list<struct<event_id int64, basis dict, scope dict>>` | no |

Declared limits: Scored date and title matches arrive with the native matcher; gpo_hearing_videos.csv stays a parity oracle until then

### `committee_records`

One document link in a meeting record; a vote row is a document link, not a ballot or tally. Identity `{"fields":["record_key"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:1914`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `record_key` | `string` | no |
| `event_id` | `int64` | no |
| `kind` | `dict` | no |
| `bill` | `string` | yes |
| `number` | `string` | yes |
| `sponsor_bioguide` | `dict` | yes |
| `amendment_type` | `dict` | yes |
| `enbloc` | `string` | yes |
| `source_description` | `string` | yes |
| `url` | `string` | yes |
| `record_sha` | `fixed[32]` | no |
| `ordinal` | `int32` | no |

### `meeting_coverage`

One aspect of one meeting: recording, transcript, documents, witnesses or captions. Identity `{"fields":["event_id","aspect"],"scope":"published identifier","validation":"native publication key checks","kind":"primary_key"}`. `model/registries/release-schema.json:2004`.

| Field | Declared type | Nullable |
| --- | --- | --- |
| `event_id` | `int64` | no |
| `aspect` | `dict` | no |
| `state` | `dict` | no |
| `basis` | `dict` | no |
| `count` | `int32` | no |
| `reason` | `dict` | yes |

## All relationship definitions

[] denotes list elements. Cardinality spans all rows/list elements. Nullable can be absent; unresolved_allowed preserves bounded coverage rather than fabricating target rows. Exact scope/meaning remain authoritative in cited registry.

| ID | Source → target | Cardinality | Nullable / resolution / match | Source |
| --- | --- | --- | --- | --- |
| `document_detail` | `list.list_row` → `detail.list_row` | one-to-one | False / required / equal | `model/registries/release-schema.json:2064` |
| `document_public_link` | `detail.link_key` → `links.link_key` | many-to-one | True / required / equal | `model/registries/release-schema.json:2085` |
| `links_document` | `links.list_row` → `list.list_row` | many-to-one | False / required / equal | `model/registries/release-schema.json:2106` |
| `urls_document` | `urls.list_row` → `list.list_row` | many-to-one | False / required / equal | `model/registries/release-schema.json:2127` |
| `sources_document` | `sources.list_row` → `list.list_row` | many-to-one | False / required / equal | `model/registries/release-schema.json:2148` |
| `recoveries_document` | `recoveries.list_row` → `list.list_row` | many-to-one | False / required / equal | `model/registries/release-schema.json:2169` |
| `document_meetings` | `list.meeting_keys[]` → `meetings.event_id` | many-to-many | True / required / decimal_string_to_integer | `model/registries/release-schema.json:2190` |
| `document_committees` | `list.committee_keys[]` → `committees.system_code` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2211` |
| `document_bills` | `list.measure_keys[]` → `bills.bill_id` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2232` |
| `meeting_bills` | `meetings.subject_keys[]` → `bills.bill_id` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2253` |
| `document_nominations` | `list.measure_keys[]` → `nominations.nomination_id` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2274` |
| `meeting_nominations` | `meetings.subject_keys[]` → `nominations.nomination_id` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2295` |
| `document_members` | `list.bioguide_ids[]` → `members.bioguide_id` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2316` |
| `witness_submitted_documents` | `list.witness_keys[]` → `witnesses.witness_key` | many-to-many | True / required / equal | `model/registries/release-schema.json:2337` |
| `document_editions` | `list.version_keys[]` → `list.version_keys[]` | many-to-many | True / unresolved_allowed / shared_list_value | `model/registries/release-schema.json:2358` |
| `meeting_committees` | `meetings.committees[].system_code` → `committees.system_code` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2379` |
| `meeting_transcript_documents` | `meetings.transcripts[].list_row` → `list.list_row` | many-to-many | True / required / equal | `model/registries/release-schema.json:2400` |
| `meeting_recordings` | `meetings.videos[].video_key` → `recordings.video_key` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2421` |
| `recording_meetings` | `recordings.event_ids[]` → `meetings.event_id` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2442` |
| `witness_meeting` | `witnesses.event_id` → `meetings.event_id` | many-to-one | True / unresolved_allowed / equal | `model/registries/release-schema.json:2463` |
| `witness_transcript_documents` | `witnesses.package_id` → `detail.package_id` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2484` |
| `witness_member` | `witnesses.bioguide_id` → `members.bioguide_id` | many-to-one | True / unresolved_allowed / equal | `model/registries/release-schema.json:2505` |
| `committee_parent` | `committees.parent_system_code` → `committees.system_code` | many-to-one | True / unresolved_allowed / equal | `model/registries/release-schema.json:2526` |
| `roster_committee` | `rosters.system_code` → `committees.system_code` | many-to-one | False / unresolved_allowed / equal | `model/registries/release-schema.json:2547` |
| `roster_member` | `rosters.bioguide_id` → `members.bioguide_id` | many-to-one | False / unresolved_allowed / equal | `model/registries/release-schema.json:2568` |
| `bill_sponsor` | `bills.sponsor_bioguide_id` → `members.bioguide_id` | many-to-one | True / unresolved_allowed / equal | `model/registries/release-schema.json:2589` |
| `amendment_sponsor` | `bills.amendments[].sponsor_bioguide_id` → `members.bioguide_id` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2610` |
| `bill_activity_committee` | `bills.committee_activities[].system_code` → `committees.system_code` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2631` |
| `bills_committees` | `bills.committees[]` → `committees.system_code` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2652` |
| `bills_votes` | `bills.floor_votes[].vote_id` → `external:spicy-regs roll-call-votes.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:2673` |
| `nominations_committees` | `nominations.committees[]` → `committees.system_code` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2691` |
| `nominations_votes` | `nominations.floor_votes[].vote_id` → `external:spicy-regs roll-call-votes.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:2712` |
| `nomination_transcript_documents` | `nominations.transcripts[]` → `detail.package_id` | many-to-many | True / unresolved_allowed / equal | `model/registries/release-schema.json:2730` |
| `document_body` | `detail.saved_body,saved_suffix` → `external:archive body store.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:2751` |
| `alternate_bodies` | `detail.alternates[].body,alternates[].suffix` → `external:archive body store.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:2770` |
| `recovery_body` | `recoveries.body,suffix` → `external:archive body store.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:2789` |
| `recording_tracks` | `recordings.tracks[].body,tracks[].suffix` → `external:archive body store.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:2808` |
| `member_lis` | `members.cross_ids.lis` → `external:Senate LIS.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:2827` |
| `member_opensecrets` | `members.cross_ids.opensecrets` → `external:OpenSecrets.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:2845` |
| `member_govtrack` | `members.cross_ids.govtrack` → `external:GovTrack.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:2863` |
| `member_icpsr` | `members.cross_ids.icpsr` → `external:ICPSR.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:2881` |
| `member_wikidata` | `members.cross_ids.wikidata` → `external:Wikidata.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:2899` |
| `member_fec` | `members.cross_ids.fec[]` → `external:FEC.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:2917` |
| `bill_cbo_publications` | `bills.cbo_estimates[].publication_id` → `external:CBO publications.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:2935` |
| `bill_amendments` | `bills.amendments[].amendment_id` → `external:spicy-regs amendments.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:2953` |
| `document_package` | `detail.package_id` → `external:GovInfo packages.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:2971` |
| `meeting_transcript_packages` | `meetings.transcripts[].package_id` → `external:GovInfo packages.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:2989` |
| `witness_package` | `witnesses.package_id` → `external:GovInfo packages.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:3007` |
| `nomination_packages` | `nominations.transcripts[]` → `external:GovInfo packages.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:3025` |
| `source_address` | `sources.url` → `external:web URL.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:3043` |
| `source_listing_page` | `sources.listed_on` → `external:web URL.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:3061` |
| `recovery_address` | `recoveries.recovered_url` → `external:web URL.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:3079` |
| `witness_page` | `witnesses.page_url` → `external:web URL.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:3097` |
| `witness_key_map_successor` | `witness_key_map.witness_key` → `witnesses.witness_key` | many-to-one | True / required / equal | `model/registries/release-schema.json:3115` |
| `witness_key_map_candidates` | `witness_key_map.candidate_keys[]` → `witnesses.witness_key` | many-to-many | True / required / equal | `model/registries/release-schema.json:3136` |
| `meeting_video_address` | `meetings.videos[].url` → `external:web URL.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:3157` |
| `committee_website` | `committees.website` → `external:web URL.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:3175` |
| `capture_request_address` | `url_state.requested_url` → `external:web URL.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:3193` |
| `capture_canonical_address` | `url_variants.canonical_url` → `external:web URL.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:3211` |
| `capture_variant_address` | `url_variants.variant_url` → `external:web URL.` | many-to-one | True / external / identifier | `model/registries/release-schema.json:3229` |
| `meeting_treaties` | `meetings.subject_keys[]` → `external:Congress.gov treaties.` | many-to-many | True / external / identifier | `model/registries/release-schema.json:3247` |
| `video_channel` | `videos.handle` → `channels.handle` | many-to-one | False / unresolved_allowed / equal | `model/registries/release-schema.json:3265` |
| `match_meeting` | `recording_matches.event_id` → `meetings.event_id` | many-to-one | True / required / equal | `model/registries/release-schema.json:3286` |
| `match_meeting_associations` | `recording_matches.meeting_links[].event_id` → `meetings.event_id` | many-to-many | False / required / equal | `model/registries/release-schema.json:3307` |
| `match_recording` | `recording_matches.video_key` → `videos.video_key` | many-to-one | True / unresolved_allowed / equal | `model/registries/release-schema.json:3328` |
| `committee_record_meeting` | `committee_records.event_id` → `meetings.event_id` | many-to-one | False / required / equal | `model/registries/release-schema.json:3349` |
| `committee_record_sponsor` | `committee_records.sponsor_bioguide` → `members.bioguide_id` | many-to-one | True / unresolved_allowed / equal | `model/registries/release-schema.json:3370` |
| `coverage_meeting` | `meeting_coverage.event_id` → `meetings.event_id` | many-to-one | False / required / equal | `model/registries/release-schema.json:3391` |
| `channel_committee` | `channels.system_code` → `committees.system_code` | many-to-one | False / unresolved_allowed / equal | `model/registries/release-schema.json:3412` |
| `retired_link_successor` | `retired_links.successor_key` → `links.link_key` | many-to-one | True / required / equal | `model/registries/release-schema.json:3433` |

Witnesses are source occurrences, not deduplicated people; own submitted URLs differ from package transcript participation. Committee attribution is not authorship. Committee vote/amendment records are document links, not ballots or floor amendments. Locator/match is not held footage; package context not full event coverage. Shared endpoint keys identify editions; alternates identify formats of one edition. Preserve independent conflicting observations and exact unknown/pending states.

## Recipe and pinned upstream census

| Recipe | Required tables | Parameters | Source |
| --- | --- | --- | --- |
| `bill_documents` | list, detail | bill_id | `model/registries/release-schema.json:3456` |
| `bill_hearing_transcripts` | meetings, list, detail | bill_id | `model/registries/release-schema.json:3481` |
| `hearing_documents` | list, detail, meetings | event_id | `model/registries/release-schema.json:3510` |
| `hearing_dossier` | meetings, witnesses, list, detail, recording_matches | event_id | `model/registries/release-schema.json:3535` |
| `witness_documents` | list, detail, witnesses | witness_key | `model/registries/release-schema.json:3567` |
| `witness_transcripts` | witnesses, detail, list | witness_key | `model/registries/release-schema.json:3593` |
| `witness_by_any_key` | witnesses, witness_key_map | witness_key | `model/registries/release-schema.json:3619` |
| `committee_roster` | rosters, committees, members | system_code, congress | `model/registries/release-schema.json:3643` |
| `nomination_transcripts` | nominations, detail, list | nomination_id | `model/registries/release-schema.json:3672` |
| `bill_votes` | bills | bill_id | `model/registries/release-schema.json:3697` |
| `nomination_votes` | nominations | nomination_id | `model/registries/release-schema.json:3719` |
| `recording_tracks` | recordings | event_id | `model/registries/release-schema.json:3739` |
| `document_editions` | list | list_row | `model/registries/release-schema.json:3762` |
| `meeting_recordings` | recording_matches | event_id | `model/registries/release-schema.json:3784` |
| `channel_unmatched_videos` | videos, recording_matches | handle | `model/registries/release-schema.json:3807` |
| `coverage_counts` | meeting_coverage | aspect | `model/registries/release-schema.json:3830` |

Execute every discovered recipe via actual replacement query_sql. Preserve declared grain, hidden exclusion, deduplicated transcript documents and supporting meeting IDs; unrelated nested lists must not multiply results.

- `bill_actions`: bill-family/bill_actions keyed ['bill_id']. One recorded action on a bill. Limits: bills carries only the latest action: a summary is not a history.. `model/registries/release-schema.json:3854`.
- `bill_cosponsors`: bill-family/bill_cosponsors keyed ['bill_id', 'bioguide_id']. One cosponsorship. Limits: bills does not carry cosponsors.. `model/registries/release-schema.json:3870`.
- `member_votes`: roll-call-votes/member_votes keyed ['vote_id', 'bioguide_id']. One member ballot. Limits: Local floor_votes hold totals, not ballots.. `model/registries/release-schema.json:3891`.
- `roll_call_votes`: roll-call-votes/roll_call_votes keyed ['vote_id']. One roll-call vote. Limits: Includes votes not tied to a local bill or nomination.. `model/registries/release-schema.json:3916`.
- `amendments`: amendments/amendments keyed ['amendment_id']. One floor amendment. Limits: Coverage is limited by upstream; committee_records holds different, committee-stage documents.. `model/registries/release-schema.json:1403`.
- `nominations`: nominations/nominations keyed ['congress', 'number', 'part_number']. One nomination part. Limits: Coverage is limited by upstream; local nominations cover what that generation holds.. `model/registries/release-schema.json:2282`.
- `committee_assignments`: committee-rosters/committee_assignments keyed ['congress', 'system_code', 'bioguide_id']. One committee assignment. Limits: Schema supports 113th–119th Congress committee and subcommittee assignments; populated only for the Congresses the pinned generation holds, which rosters.parquet coverage congress_start and congress_end bound.. `model/registries/release-schema.json:3965`.

These seven descriptors are discovery-only; MCP does not read external detail. Actual model imports 12 exact tables across six generations:

- `spicy_amendments` → `generations/amendments/75c96edc20e43499f45efb19c135344cb849a801ce0f0abec1d0861b755698e2/amendments.parquet`, rows=7119, bytes=143880, sha256=00d56d0b694f66bafd10df8c88999d8fbc9dffca62507ee2e7c2a4f2409c1a09; `model/jobs/spicy-regs/spicy-regs.json:12`.
- `spicy_bill_committee_activities` → `generations/bill-family/f719442c6a814666c5747624ef8a52da002bc2982f4ebd7f2be990f86bc38d42/bill_committee_activities.parquet`, rows=341157, bytes=3266366, sha256=d748ad8a48e3c039e12f74dd0629574776adbbb9b9f306757eb758e049823422; `model/jobs/spicy-regs/spicy-regs.json:20`.
- `spicy_bill_committees` → `generations/bill-family/f719442c6a814666c5747624ef8a52da002bc2982f4ebd7f2be990f86bc38d42/bill_committees.parquet`, rows=286771, bytes=2131507, sha256=1095c541e6943146f3a4a41f14d5ad5d202e357db8368767ca7428f7236d45c6; `model/jobs/spicy-regs/spicy-regs.json:28`.
- `spicy_bill_vote_references` → `generations/bill-family/f719442c6a814666c5747624ef8a52da002bc2982f4ebd7f2be990f86bc38d42/bill_vote_references.parquet`, rows=19766, bytes=204179, sha256=25abe460b4571b41c49c1f1fca85bb32d7d5de57421f8657e603be5bc5108f0b; `model/jobs/spicy-regs/spicy-regs.json:36`.
- `spicy_cbo_cost_estimates` → `generations/bill-family/f719442c6a814666c5747624ef8a52da002bc2982f4ebd7f2be990f86bc38d42/cbo_cost_estimates.parquet`, rows=14843, bytes=982842, sha256=9bd62ada710f2d3884bc3c72daf0a372723c266d6f74b77da1fe1741a665c234; `model/jobs/spicy-regs/spicy-regs.json:44`.
- `spicy_committee_assignments` → `generations/committee-rosters/5f031073f8329cd49c5a6c43470e26178de5ef21362ad6d43a85ead6fab39da3/committee_assignments.parquet`, rows=2973, bytes=40433, sha256=e0cdb2ebc07c418a4730111bd964304759cc3d161d61f208961b7f8557d4ce48; `model/jobs/spicy-regs/spicy-regs.json:52`.
- `spicy_committees` → `generations/committee-rosters/5f031073f8329cd49c5a6c43470e26178de5ef21362ad6d43a85ead6fab39da3/committees.parquet`, rows=817, bytes=90551, sha256=75f27be725db2f4aeeab48c5b8d04bd2876a96877f65fe3c50445f1569abc577; `model/jobs/spicy-regs/spicy-regs.json:60`.
- `spicy_congress_bills` → `generations/bill-family/f719442c6a814666c5747624ef8a52da002bc2982f4ebd7f2be990f86bc38d42/congress_bills.parquet`, rows=422024, bytes=35016544, sha256=4b7ae92b7e706934dccbc090cd562c6d5c938d125e6d96aa7e35f7a367ee209d; `model/jobs/spicy-regs/spicy-regs.json:68`.
- `spicy_member_terms` → `generations/members/29718daf2daec8dd84dfcbfdb1f4bc7ed5daa439e6567294ef4b59cee3b58764/member_terms.parquet`, rows=45535, bytes=234901, sha256=dc8fd9f024f60a29f61bbb01ebddc28418d8f6c1d680fe09eca4d283a9887fb6; `model/jobs/spicy-regs/spicy-regs.json:76`.
- `spicy_members` → `generations/members/29718daf2daec8dd84dfcbfdb1f4bc7ed5daa439e6567294ef4b59cee3b58764/members.parquet`, rows=12770, bytes=395401, sha256=ef0dace053bd888bc5f696e1cd8dceaed06f4d1ba379807bf835a0b2ff175579; `model/jobs/spicy-regs/spicy-regs.json:84`.
- `spicy_nominations` → `generations/nominations/d17c43e1bc6773cff17dc3ac6c7d79f5938ba9fa105a837e96deda23c91255f3/nominations.parquet`, rows=2287, bytes=95904, sha256=55df655f456f0ef2844e967a079a648d56210f45630c20983147ffe1a344cf67; `model/jobs/spicy-regs/spicy-regs.json:92`.
- `spicy_roll_call_votes` → `generations/roll-call-votes/e7cdd80d9eecbf13ce172ce076c9a5df77fd418c97fb80d13393ce6ab595ace0/roll_call_votes.parquet`, rows=30702, bytes=1725008, sha256=f6a12daa839ad21b5ae7683f244b827f64730add5b4782b8d35924cb0d62887f; `model/jobs/spicy-regs/spicy-regs.json:100`.

## Route, transport and consumer API census

Six MCP tools: get_dataset_info/search_documents/get_document/search_entities/get_entity/query_sql (`apps/explorer_mcp/src/congressional_explorer_mcp/server.py:55`). Document sections summary/sources/recoveries/text/page_metadata/selected_text; entity sections record/documents; strict models `apps/explorer_mcp/src/congressional_explorer_mcp/models.py:54`. Stdio and stateless HTTP share server. Hosted /mcp exposes tools; GET / returns service/publication metadata. No separate REST data API found. CLI prepare/inspect/serve/config/check and two aliases follow in console census. Queries never silently refresh.

Site routes: /archive mounts ArchiveExplorer; /mcp and /mcp/agent.md provide setup/research guidance; /youtube-coverage report dashboard; /dashboard translates supported bookmarks or explains retired views. Homepage/projects/proposals link these. Archive params: tab/q/congress/chamber/committee/kind/hearing/subject/subject_kind/witness/member/format/sort/offset/key plus aliases (`ArchiveExplorer.tsx:68`). No current page mounts old CommitteeExplorer.

Internal browser worker request paths (not HTTP endpoints):

- `/info` → `apps/site/src/components/explorer/reader/archive-worker.ts:31`.
- `/search` → `apps/site/src/components/explorer/reader/archive-worker.ts:42`.
- `/facets` → `apps/site/src/components/explorer/reader/archive-worker.ts:49`.
- `/lookup` → `apps/site/src/components/explorer/reader/archive-worker.ts:50`.
- `/entry` → `apps/site/src/components/explorer/reader/archive-worker.ts:51`.
- `/openDocument` → `apps/site/src/components/explorer/reader/archive-worker.ts:52`.
- `/meeting` → `apps/site/src/components/explorer/reader/archive-worker.ts:72`.
- `/committee` → `apps/site/src/components/explorer/reader/archive-worker.ts:80`.
- `/witness` → `apps/site/src/components/explorer/reader/archive-worker.ts:81`.
- `/member` → `apps/site/src/components/explorer/reader/archive-worker.ts:82`.
- `/subject` → `apps/site/src/components/explorer/reader/archive-worker.ts:83`.
- `/bill` → `apps/site/src/components/explorer/reader/archive-worker.ts:84`.
- `/nomination` → `apps/site/src/components/explorer/reader/archive-worker.ts:85`.
- `/entities` → `apps/site/src/components/explorer/reader/archive-worker.ts:86`.
- `/pageMetadata` → `apps/site/src/components/explorer/reader/archive-worker.ts:87`.
- `/selectedText` → `apps/site/src/components/explorer/reader/archive-worker.ts:88`.
- `/saved` → `apps/site/src/components/explorer/reader/archive-worker.ts:89`.

The direct `openArchive` reader API additionally exposes `has/search/facets/entry/pageMetadata/selectedText/resolve/lookup/lookupRows/sourceRange/recoveryRange/versions`, table loaders `meetings/witnesses/recordings/committees/members/rosters/bills/nominations/urlState`, entity methods `getMeeting/getCommittee/getWitness/getMember/getBill/getNomination/getSubject/listEntities/openDocument`, and `retired/witnessKeyMap/locate/schema/openSaved`, with releaseId/manifest/metrics/count properties (`apps/site/src/components/explorer/reader/archive.ts:313`). These library consumers must preserve exact same supported access even when no worker request calls a helper directly.

Legacy ExplorerReader declares getQueryInfo/search/getRelated/getCoverage/getRecord/getRecords/listWitnesses/listMaterialCounts (`reader/types.ts:210`) with kind/congress/q/chamber/date/month/type/status/category/severity/participation/provider/history/access/committee/aspect/evidence/sort/direction/offset/limit. It remains compatibility/offline scope; current /archive worker has a different interface. Avoid restoring a competing current data authority.

## Whole-workspace non-archive scope

pyproject.toml:29 includes news_lake/youtube_api/committee_youtube/inflation_gsheets. They remain required. C45/C49-C54 record incomplete detailed field/relationship/consumer evidence; whole-repository completion cannot be claimed.

### News-lake

Actual schema routes 13 tables, twelve non-release (`contract/records.py:23`), despite stale CLI docstring saying 10 raw datasets. Explicit JSON nulls forbidden. Field IDs/pinned authoritative storage schema and schema evolution also require qualification.

| Kind/table | Key / mutation | Required | Declared fields |
| --- | --- | --- | --- |
| `outlet` / `news.outlets` | ['id'] / upsert | kind, id, recorded_at, name, domains | `kind:outlet`; `id:id`; `recorded_at:instant`; `name:label`; `domains:list<string>`; `feed_urls:list<http_url>`; `country_code:string`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:179` |
| `capture` / `news.captures` | ['id'] / append | kind, id, recorded_at, provider, request_url, observed_at, access, status | `kind:capture`; `id:id`; `recorded_at:instant`; `provider:label`; `request_url:http_url`; `observed_at:instant`; `http_status:integer`; `payload_uri:uri`; `payload_hash:hash`; `media_type:label`; `access:string`; `rights_basis:label`; `retain_until:instant`; `status:string`; `error_code:label`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:221` |
| `discovery` / `news.discoveries` | ['id'] / append | kind, id, recorded_at, capture_id, item_id, provider, url, observed_at, mode | `kind:discovery`; `id:id`; `recorded_at:instant`; `capture_id:id`; `item_id:id`; `provider:label`; `external_id:label`; `query_revision:label`; `feed_url:http_url`; `url:http_url`; `observed_at:instant`; `mode:string`; `reported_title:string`; `reported_publication:publication`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:243` |
| `item` / `news.items` | ['id'] / upsert | kind, id, recorded_at, canonical_url, url_aliases, content_type, first_seen_at | `kind:item`; `id:id`; `recorded_at:instant`; `outlet_id:id`; `canonical_url:http_url`; `url_aliases:list<http_url>`; `content_type:string`; `first_seen_at:instant`; `current_version_id:id`; `superseded_by:id`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:261` |
| `version` / `news.versions` | ['id'] / append | kind, id, recorded_at, item_id, capture_id, run_id, title, publication, access | `kind:version`; `id:id`; `recorded_at:instant`; `item_id:id`; `capture_id:id`; `run_id:id`; `title:string`; `publication:publication`; `text:string`; `text_hash:hash`; `access:string`; `rights_basis:label`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:295` |
| `entity` / `news.entities` | ['id'] / upsert | kind, id, recorded_at, entity_type, name, aliases, identifiers | `kind:entity`; `id:id`; `recorded_at:instant`; `entity_type:string`; `name:label`; `aliases:list<name>`; `identifiers:list<identifier>`; `tenures:list<tenure>`; `affiliations:list<affiliation>`; `evidence_capture_ids:list<id>`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:319` |
| `identity_decision` / `news.identity_decisions` | ['id'] / append | kind, id, recorded_at, action, decided_by, reason | `kind:identity_decision`; `id:id`; `recorded_at:instant`; `action:string`; `left_id:id`; `right_id:id`; `prior_decision_id:id`; `decided_by:label`; `reason:label`; `evidence_capture_ids:list<id>`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:354` |
| `run` / `news.runs` | ['id'] / append | kind, id, recorded_at, processor, processor_version, config_hash, input_hash, inputs, mode, status, started_at, finished_at | `kind:run`; `id:id`; `recorded_at:instant`; `processor:label`; `processor_version:label`; `model_version:label`; `config_hash:hash`; `input_hash:hash`; `inputs:list<input_ref>`; `mode:string`; `status:string`; `started_at:instant`; `finished_at:instant`; `reason:label`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:399` |
| `mention` / `news.mentions` | ['id'] / append | kind, id, recorded_at, version_id, run_id, surface, resolution, aboutness, occurrences | `kind:mention`; `id:id`; `recorded_at:instant`; `version_id:id`; `run_id:id`; `surface:label`; `resolution:string`; `entity_id:id`; `identity_confidence:score`; `aboutness:string`; `aboutness_confidence:score`; `occurrences:list<span>`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:433` |
| `classification` / `news.classifications` | ['id'] / append | kind, id, recorded_at, version_id, run_id, dimension, taxonomy_version | `kind:classification`; `id:id`; `recorded_at:instant`; `version_id:id`; `run_id:id`; `dimension:label`; `taxonomy_version:label`; `target_entity_id:id`; `confidence:score`; `value_string:string`; `value_number:number`; `value_boolean:boolean`; `value_strings:list<string>`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:460` |
| `story` / `news.stories` | ['id'] / append | kind, id, recorded_at, run_id | `kind:story`; `id:id`; `recorded_at:instant`; `run_id:id`; `label:label`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:473` |
| `story_member` / `news.story_members` | ['id'] / append | kind, id, recorded_at, story_id, version_id, run_id | `kind:story_member`; `id:id`; `recorded_at:instant`; `story_id:id`; `version_id:id`; `run_id:id`; `score:score`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:488` |
| `release` / `news.releases` | ['id'] / append | kind, id, recorded_at, contract_version, snapshots, selections, checkpoints | `kind:release`; `id:id`; `recorded_at:instant`; `contract_version:0.1.0`; `snapshots:list<snapshot>`; `selections:list<selection>`; `checkpoints:list<checkpoint>`; `packages/news_lake/src/news_lake/contract/schema/news-lake.schema.json:509` |

CLI publish/views/export/compact-lifecycle; views full/incremental/verify-oracle (`news_lake/cli.py:208`). Three bridges entity_roots/selected_mentions/survivor_items; two public views politician_articles/coverage_daily (`storage/docspec/views.py:31`), with reusable native internal join/group/count stages. Required person-root/current-item/release grain, selected-only zero-output/pending runs, code-point overlap/adjacent spans, decision retractions, survivor corrections, precision-aware/discovery/undated dates and cross-date identical-text syndication. Pure Python/PyIceberg are differential reference oracles, not independent raw proof.

contract/semantics.py:check_corpus validates FK kinds, run input coverage, exact text hash/spans, intervals, current-version/supersede ownership, story/member/run consistency, complete release snapshots/selections/checkpoints, identity graph cycles/conflicts/retractions and credentials. Full nested field-path/cardinality catalog and authentic release inputs remain unrecovered C49-C51 scope. Live provider/extractor/pilot/full retention claims are not established.

### YouTube, Committee Explorer export and reports

youtube-fetch writes per-committee TinyDB youtube_channels and literal youtube_videos_{handle}; shared decoder preserves insertion order/duplicates/unknown fields. youtube-analyze eight EventIdReport fields: committee_name:string, handle:string, total_videos:int, missing_event_id:int, congress_number:int, control:string, chamber:string, with_captions:int (`analyze/main.py:39`). Playlist-added versus video-publication date never substitutes; UTC Congress ranges half-open; invalid/missing/naive time unknown. Dashboard reads seven fields, ignoring with_captions (`dashboard/data.ts:60`).

youtube-captions retains tracks/<video>.vtt, <video>.txt, captions_index.csv(video_id,kind,characters), metadata/<video>.<sha>.info.json.gz and caption_receipts/<video>.json. manual/auto/none/error is English-WebVTT observation scope; selected_track/track_files and last_successful survive failure (`captions/main.py:41`). C48 dedicated tests/authentic tracks remain open.

Baseline committee-explorer-export is a maintained local consumer/producer: committees/meetings/appearances/materials/issues/source evidence, evidence shards, coverage/file discovery, exact snapshots/source scopes, stable IDs/issue history and CURRENT.json. New JSON export is explicitly refused by export.py:380-381, and CLI choices are Parquet-only at :1111; test_explorer_reuse.py:134-138 asserts refusal. Historical readback is separate: load_previous at export.py:178-203 can read verified retained committee_explorer.records/sources JSON partitions and migrate issue history when SQLite history is absent. The greenfield decision retires old consumer-format readback as an adoption obligation; retained raw evidence and issue history still need a supported current-format path. This does not authorize successful new JSON export. Unchanged Parquet reuse does not establish changed-input partial updates. browser.verify/package also validate pointer/manifest/partition identities, retain Parquet bytes while excluding download and legacy meeting/print-decision parts, derive a distribution identity and enforce a 900MB budget (`apps/committee_youtube/src/committee_explorer/browser.py:13`, `:35`); query.write_queries emits browse metadata/indexes (`query.py:11`). Full nested schema/artifact/machine-reader census remains C45 scope (`committee_explorer/parquet.py:126`, `export.py:994`). Weekly House/Senate/GPO/transcript/inventory reports are distinct required consumers named below; detailed acquisition/report routes assigned to source inventory.

### Inflation CSV and Google Sheets

README-stated BLS_CPI=CPIData!A1:M1000 feeds FLOATYEARDATE/INFLATION; INFLATION_SOURCES=InflationSources!A1:I2000 imports comparison. Remote sheet not opened; README is not current deployed formula proof. historical-cpi.csv holds year/month CPI levels; inflation-sources.csv monthly month-start YoY% bls_yoy/fred_median/fred_trimmed/fred_sticky, optional adobe/pricestats, optional aggregate. Daily sources last monthly reading; aggregate renormalizes present weights and remains derived/opt-in.

No app tests found. All-sources-down returns exit 0 without changing prior CSV (`fetch-inflation-sources.py:146`), contrary to workflow comment requiring BLS/FRED. CPI updater replaces entire duplicate year (`fetch-cpi-convert-csv.py:57`), potentially erasing months omitted in partial response. These observed semantics require policy/consumer qualification; no fix or live comparison ran.

## Console entry points

Exact project.scripts definitions follow. Module CLIs in viewer_publication/corpus_recovery/lake additionally remain source/lifecycle inventory obligations; absence here is not removal.

| Command | Callable | Source | Capability |
| --- | --- | --- | --- |
| `committee-meeting-schema` | `committee_meeting.main:main` | `packages/committee_meeting/pyproject.toml:10` | C54 |
| `house-committee-sites` | `congress_api.cli.house_sites:parse_args_and_run` | `packages/congress_api/pyproject.toml:37` | C54 |
| `house-meeting-records` | `congress_api.cli.house:parse_args_and_run` | `packages/congress_api/pyproject.toml:38` | C54 |
| `senate-meeting-records` | `congress_api.cli.senate:parse_args_and_run` | `packages/congress_api/pyproject.toml:39` | C54 |
| `meeting-inventory` | `congress_api.cli.inventory:parse_args_and_run` | `packages/congress_api/pyproject.toml:40` | C54 |
| `gpo-fetch` | `congress_api.cli.gpo_fetch:parse_args_and_run` | `packages/congress_api/pyproject.toml:41` | C54 |
| `gpo-match` | `congress_api.cli.gpo_match:parse_args_and_run` | `packages/congress_api/pyproject.toml:42` | C54 |
| `senate-captions` | `congress_api.cli.senate_captions:parse_args_and_run` | `packages/congress_api/pyproject.toml:43` | C54 |
| `hearing-transcribe` | `congress_api.cli.transcribe:parse_args_and_run` | `packages/congress_api/pyproject.toml:44` | C54 |
| `gpo-transcripts` | `congress_api.cli.gpo_transcripts:parse_args_and_run` | `packages/congress_api/pyproject.toml:45` | C54 |
| `congress-meetings` | `congress_api.cli.meetings:parse_args_and_run` | `packages/congress_api/pyproject.toml:46` | C54 |
| `congress-committees` | `congress_api.cli.committees:parse_args_and_run` | `packages/congress_api/pyproject.toml:47` | C54 |
| `house-naming` | `house_naming.cli:main` | `packages/house-naming/pyproject.toml:22` | C54 |
| `house-naming-corpus` | `house_naming.filename_corpus:main` | `packages/house-naming/pyproject.toml:23` | C54 |
| `news-lake` | `news_lake.cli:main` | `packages/news_lake/pyproject.toml:20` | C49-C51 |
| `youtube-fetch` | `youtube_api.fetch.main:parse_args_and_run` | `packages/youtube_api/pyproject.toml:17` | C46 |
| `youtube-analyze` | `youtube_api.analyze.main:parse_args_and_run` | `packages/youtube_api/pyproject.toml:18` | C47 |
| `youtube-captions` | `youtube_api.captions.main:parse_args_and_run` | `packages/youtube_api/pyproject.toml:19` | C48 |
| `committee-explorer-export` | `committee_explorer.export:main` | `apps/committee_youtube/pyproject.toml:21` | C45 |
| `congress-explorer-mcp` | `congressional_explorer_mcp.cli:main` | `apps/explorer_mcp/pyproject.toml:20` | C21 |
| `congressional-explorer-mcp` | `congressional_explorer_mcp.cli:main` | `apps/explorer_mcp/pyproject.toml:21` | C21 |

## Capability acceptance matrix

consumer-capabilities.json has exact source/test evidence, proposed owner, plan-only command/case, authentic retained evidence and gaps for all 54 rows. Proposed ddk_consumer_acceptance.py harness is not implemented or qualified. Bind accepted-consumer-inputs.json to accepted immutable authentic raw/body/receipt cohorts/releases under main .cache/archive-release and label synthetic fixtures separately before implementation. Actual baseline/candidate entry points must run in fresh processes, compare exact values/types/keys/multiplicity/refusal-empty-pending states, and detect planted plausible faults with a separate raw-check reviewer. Existing baseline tests are not candidate proof.

| ID | Required behavior | Acceptance case and expected proof |
| --- | --- | --- |
| C01 | Preserve all 23 public tables, fields, nested types, nullability and grains | Compare all output schemas and rows; include fixed[8]/fixed[32], int64 beyond JS safe range, required lists, nullable values and published empty table. No missing field, coercion or lost multiplicity. |
| C02 | Select eight lake schemas by exact snapshot/schema/UUID/parser/catalog versions | Retain old/current versions per body/parser/source and a qualified older reading. Select one applicable version before joins/restamp; uncovered version refuses or remains pending. |
| C03 | Distinguish bytes, editions, formats, endpoints, sources and recovery occurrences | Same bytes/two URLs, two editions/one URL, alternate PDF/HTML, duplicate ZIP member names and related recovery. Preserve exact occurrence/provenance; related files never become original. |
| C04 | Publish all 70 relationship definitions and version/availability semantics | Current/absent/unknown metadata and future relationship with missing target. Preserve endpoints/cardinality/scope; do not reconstruct missing metadata from current code. |
| C05 | Execute all 16 published recipes with correct result grains | Discover then execute every recipe through candidate query_sql with discovered keys; duplicate endpoint and transcript paths retain one document and supporting meeting IDs; avoid nested-list multiplication. |
| C06 | Run all six required invariant suites and preserve refused/empty/pending meaning | Plant duplicate key, null required list, missing nested target, plausible wrong value and absent suite. Independently detect each fault; valid published empty remains available. Separate reviewer confirms planted raw case. |
| C07 | Read current or direct historical immutable release with release-bound citations | Open two retained direct manifests in separate caches while current advances. Exact old bytes stay readable and references cannot silently cross releases. |
| C08 | Prepare/update/rollback atomically while retaining running readers and completed transfers | Interrupt after verified asset; simulate disk full and corrupt old object; update/rollback with old reader alive. Keep previous selection, reuse completed immutable assets, protect live references. |
| C09 | Selective correction/delete closure and unaffected-row reuse | Fixed correction across growing population; unchanged rerun; same-stamp omission versus explicit empty/later omission; changed dedup winner. Preserve unaffected values and correct all downstream/retirement effects; measure opens/bytes/rewrites. |
| C10 | MCP get_dataset_info discovers controls/tables/keys/coverage/relations/recipes/upstream pins | Exercise all selectors, conflicting selectors and oversized controls. Examples never execute during discovery; missing tables explicit and response <=128 KiB. |
| C11 | MCP search_documents performs metadata search and exact filter intersection | Combine text/congress/format/kind/committee/meeting/measure/witness/member. Match exact keys and normalization; strict hidden flag; metadata search is not body search. |
| C12 | MCP document summaries resolve public/hidden/reviewed keys and date evidence | Read live, hidden, retired, absent and wrong-release keys. Preserve source/body/alternate/date basis/status/review values; defer large text. |
| C13 | MCP pages ordered source/recovery occurrences and authored identity notes | More than one page, duplicate URL with distinct context/member, null authored note. Preserve order, ordinals, kind and multiplicity; no invented identity finding. |
| C14 | Read publisher declarations and selected text with body/selector/reader evidence | Conflicting/rejected/relative declarations, partial/unreadable result, omitted text and offset slices. Keep literal versus selected evidence, exact citations and unavailable state. |
| C15 | Read verified PDF/HTML/XML/plain bodies and bounded per-document snippets/cache | Authentic formats plus wrong digest, redirect, gzip bomb, regex timeout, cache mutation, unsupported format and scanned PDF. Exact pages/offsets; 64MiB decode/128KiB reply; no invented OCR. |
| C16 | MCP entity search uses published identity and exact scalar types/case handling | Every keyed family, future keyed table, compound roster, huge integer, bool, mixed-case handle and no-text family. Refuse lossy IDs/nested/BLOB/unknown filters; address tables stay document routes. |
| C17 | MCP single-key entities and directly associated document pages | Each single-key family, absent and compound keys; direct witness submitted documents versus package transcript. No meeting-wide document ownership inference; exact direct relationship preserved. |
| C18 | MCP native read-only SQL joins/nested types/parameters and bounded typed output | Join all families; lists/decimal/int64/BLOB/null; writes/network/extensions/config, duplicate columns, giant row and truncation. One SELECT, <=200 SQL rows, <=128KiB; precision preserved. |
| C19 | MCP pagination binds normalized query/limit/release and enumerates rows once | Traverse documents/entities/sources/recoveries; changed query/release/limit refuses; equivalent normalized integer query retains valid cursor and complete stable order. |
| C20 | Worker offline isolation, memory/spill, queue, timeout/cancellation/restart and scratch cleanup | Cancel active/queued work, kill parent/worker, overflow queue, retry. Respect 512MB DuckDB memory/512MB spill; only owned scratch removed; no external reads/writes. |
| C21 | Desktop/stdio first-use setup and CLI prepare/inspect/config/check plus aliases | All supported client configs, first-use retry/concurrency/cancel, corrupt selection and explicit refresh. One initializer; exact selected release; no silent query refresh/cache deletion. |
| C22 | Hosted stateless HTTP MCP and deployment-pinned cold-start replicas | Loopback / and /mcp; independent clients and restarts; origins/methods/chunked >64KiB/rate/upstream failure. Preserve 403/404/405/413/429/503/Retry-After and same selected tools/release as stdio. |
| C23 | Browser manifest/range/shard integrity, release pinning and one reload on drift | Retained manifest and sharded fixture; bad bytes/ranges/footer, missing asset, pointer change and retry. Half-open absolute positions preserve attachments; exactly one pointer recheck/reload; failed cache retryable. |
| C24 | Site metadata/bill-code/URL search, facets, entity intersections, sort and paging | Every filter, committee descendants, bill spelling, Unicode/dot-path/query URL, blank title, date/title order and cancel. Exact keys/order/count; hidden excluded; credentials refused; editions retained. |
| C25 | Site document inspector shows copies/occurrences/editions/related entities and date meanings | Open row then stable key; sharded attachments, formats versus versions, suspect/undated/import day. list_row release-local; no substitution among document/page/import/capture/hearing dates. |
| C26 | Retired document redirects, removal/history notices and never-published keys | Read alias, supported successor, removal only, other address editions, never-published after correction/delete. No silent vanished links; last release/filename retained; successor must exist. |
| C27 | Site entity browse tabs/deep-link query aliases/back-forward behavior | Hearings/committees/witnesses/members/combined or typed bill/nomination subjects with q/congress/chamber/committee and offsets. Same sets/order/count and meaningful unavailable states. |
| C28 | Hearing dossier exposes current occurrences/files/transcript sources/recordings/evidence | House/Senate/closed/rescheduled, package/direct event, superseded/member/record statements and optional failure. No same-name collapse or statement-as-testimony; exact evidence uncertainty visible. |
| C29 | Committee historical names/parents/subcommittees and Congress-scoped rosters | Date/Congress name interval; parent with different prefix; unavailable roster Congress and populated seats. Exact rank/title/party; missing coverage not zero seats. |
| C30 | Witness occurrence identity, supersession and old-key unique/ambiguous/unresolved mapping | Same-name occasions, repeated observations, superseded MODS, old key candidates and package-only. Current excludes superseded only; exact history remains; no name-based identity/authorship. |
| C31 | Member terms/cross IDs/rosters/explicit appearances/sponsored bills/documents | Terms/party/state changes and linked witness/roster/bills plus missing reference catalog. Exact Bioguide and explicit participation; membership not attendance; unknown values retained. |
| C32 | Bill/nomination summaries/committee activities/votes/print packages/hearing trails | Related versions/split nomination, raw activity precision, optional hearing failure and duplicate print paths. Exact IDs/coverage; totals not ballots; committee links not floor amendments. |
| C33 | Browser optional relation states/cancel/retry and primary selection survival | Fail optional relation/display range, cancel shared consumer, retry, release drift. Primary row stays; no poisoned cache; integrity errors propagate; ready/missing/unavailable remain explicit where supported. |
| C34 | Saved file open/download uses physical suffix/media/original bytes and HLS context | Retained .pdf/.gz/raw/alternate, already-decoded gzip, large download, HLS and popup refusal. No suffix inference from display type; int64 survives clone; decode once; HLS not standalone playback. |
| C35 | Recording observations preserve original subject/evidence/conflicts and event/package scope | Direct event, print agreement, multi-sitting package context, excerpt, claimed/conflicting/unresolved and repeated URL. Keep independent observations; package locator not full event footage. |
| C36 | Five coverage aspects and explicit present/partial/claimed/unresolved/unknown/empty states | Each state, Senate page pending, unattached package witnesses, zero table versus absent table. Exactly five rows/event; zero count not absence; date bounds not complete census. |
| C37 | Seven pinned external detail descriptors and bounded local reference summaries | Discover actions/cosponsors/ballots/rollcalls/amendments/nominations/assignments; separately qualify owning catalog field/key/generation. No claim local MCP reads external detail. |
| C38 | YouTube report dashboard filters/totals/charts and accessible table fallback | Retained CSV and all/cooperative Congress/chamber/party filters, quoted row and zero result. Independently sum report values; Event-ID regex absence is not missing official hearing. |
| C39 | Legacy dashboard bookmark forwarding and retired Coverage/Gaps notices | Old aliases/opaque event ID with one/two/no map matches, coverage/gaps, BASE_URL/hash. Only unambiguous redirect; no invented equivalence for closed views. |
| C40 | Producer parse/refusal and absent/empty/unrecognized collection semantics | Malformed XML/readable-decision/same-stamp omission/explicit empty/unrecognized/later omission. Failure not valid empty; exact source precedence and no false success. |
| C41 | Evidence-limited research aggregates and occurrence/coverage denominators | Committee/month/organization/lag/coverage/cross-chamber queries plus independent raw examples. Occurrence not deduplicated people; observed dates not population completeness; preserve unknown/refused denominators. |
| C42 | Retain honest unsupported global full-text/OCR/live comparison/person inference/attendance/monitoring | Exercise unsupported persona requests and bounded document reads. Do not promise global index, OCR, speaker alignment, demographic/name dedup, current website equality or standing alert. |
| C43 | Source-backed dates/printed metadata/page citations and retained conflicts | Retained cover disputes, package conflicts/invalid filename and exact page text. Preserve literal/source/status/claim; act year not date; package link alone not proof of quotation. |
| C44 | Read the single current public catalog and keyed-detail/list pairing without invented definitions | Require the exact public catalog/report/lock tuple and effective definitions; refuse unsupported/partial controls and present tables missing current fields. Keep one copy of repeated list/detail columns, nullable date status, retired-key history and optional-table absence. Old consumer formats are outside greenfield acceptance. |
| C45 | Committee Explorer current Parquet export, explicit retired-JSON refusal and distribution workflow | Run current Parquet export with stable IDs/source and issue history, unchanged reuse, changed inputs and interruption before CURRENT. Require explicit refusal of new JSON export before assembly. Qualify state pack/unpack, browser package/verify, exact pipeline snapshot save and Pages revision dispatch separately. Historical raw evidence/history remains required; old JSON consumer-format readback is no longer an adoption requirement. |
| C46 | YouTube fetch/cache identity and atomic durable pages for downstream readers | Retained fake channel/playlist/video pages, duplicate IDs/changed handle/unknown fields/failed channel. Preserve configured IDs/literal handles/history, atomic page completion and nonzero partial failure. |
| C47 | YouTube EventIdReport CSV with explicit playlist-added/video-publication date basis | UTC boundary/missing-invalid-naive time/multiple handles/unknown caption/failed committee. Eight exact fields; no time fallback; half-open Congress counts once; exclusions explicit nonzero outcome. |
| C48 | YouTube English caption tracks/text/index and scoped success/none/error receipts | Retained downloader metadata/track fake manual-auto-none/declared-unreadable/blocked-after-success. Error not absence; last success/timing tracks preserved; text not transcript of record; valid receipt reusable. |
| C49 | News publish/read exact immutable releases over 12 content tables plus release records | Invalid/empty batch, append/upsert, optional evolution, selections/checkpoints, crash/pending/retired/missing snapshot. Schema-owned routing, exact pins, null forbidden at record boundary, old snapshot isolation. |
| C50 | News person-root/current-item/selected-run views, corrections, undated dates and syndication | Decision/retraction/version/selected-zero/pending changes, adjacent/overlap spans, unknown dates and full versus incremental fresh process. Three bridges/two views exact; removals retract; syndication not independent reporting. |
| C51 | News authorized/expired export and consumer-visible lifecycle commands | Same release authorized/unauthorized at fixed expiry, protected old reader during compaction. Omit only policy restricted/expired payload/text; metadata kept; source immutable; published identity required. |
| C52 | Inflation CPI grid and documented Google Sheets named ranges/functions | Frozen CSV/BLS response revised year/placeholder/missing month; actual named formula integer/fractional years. Preserve CPI-level units and ratio dollars; missing unknown; exact deployed formula parity required. |
| C53 | Inflation monthly YoY comparison, optional aggregate and unavailable-source semantics | Frozen BLS/FRED/manual data, daily duplicate month/null/missing/all-down; weighted/default aggregate. Month-start YoY%, last monthly reading, no null-zero, renormalized weights, opt-in derived label and prior CSV preservation. |
| C54 | All remaining console/module/report/transcript/schema routes remain required scope | For each named command freeze arguments/offline inputs/output schemas/exit states and independently read downstream artifacts. No alias/output silently disappears; domain ownership remains while duplicated generic infrastructure is removed. |

For resource improvement, hold delta fixed as history/population grows; measure actual opens/bytes/rewrites, not function calls. Preserve previous selected result until required consumer outputs/evidence complete. Full-generation comparison, native suites and deployed readback remain later gates; sample parity cannot prove full corpus.

## All 100 persona questions kept in scope

docs/congress-explorer-personas.md describes unmeasured predicted outputs. Mapping below means route or explicit gap, not available/correct answer. C42 marks unsupported whole-corpus full-text/OCR/live comparison/person inference/monitoring; C37 external detail absent locally. Actual occurrence evidence and published limits override predicted people/coverage totals.

| Persona.question | Question / source | Capability / status |
| --- | --- | --- |
| 1.1 | What documents did the committee publish and later remove this quarter? (`docs/congress-explorer-personas.md:50`) | C12, C13, C18, C26; plan only |
| 1.2 | Which organizations supplied more than one witness across the hearings on this bill? (`docs/congress-explorer-personas.md:55`) | C16, C18, C30, C41; plan only |
| 1.3 | Show every document whose only surviving copy is a recovery — what does each `identity_note` say it actually is? (`docs/congress-explorer-personas.md:60`) | C13, C18; plan only |
| 1.4 | How many versions of this report exist, and which was the committee site actually serving? (`docs/congress-explorer-personas.md:65`) | C05, C25; plan only |
| 1.5 | Which documents on this topic vanished within 30 days of first capture? (`docs/congress-explorer-personas.md:70`) | C18, C26; plan only |
| 1.6 | What got posted in the three days surrounding that news event — by posted date, not document date? (`docs/congress-explorer-personas.md:73`) | C13, C14, C43; plan only |
| 1.7 | Which hearings have zero surviving recordings, and does `meeting_coverage` say why? (`docs/congress-explorer-personas.md:78`) | C18, C35, C36; plan only |
| 1.8 | Who testified on this bill in both chambers, in order of appearance? (`docs/congress-explorer-personas.md:83`) | C18, C30, C41, C42; unsupported gap |
| 1.9 | Trace this document's URL history — status codes, attempts, last good date. (`docs/congress-explorer-personas.md:86`) | C18; plan only |
| 1.10 | Give me a citable reference for each removed document so my editor can independently verify. (`docs/congress-explorer-personas.md:90`) | C07, C26; plan only |
| 2.1 | Did this witness actually say "[quote]" — search the verified full text of every appearance. (`docs/congress-explorer-personas.md:103`) | C15, C17, C30; plan only |
| 2.2 | Which page of the printed hearing does that statement appear on? (`docs/congress-explorer-personas.md:108`) | C15; plan only |
| 2.3 | Was it spoken in the hearing or only submitted in writing? (`docs/congress-explorer-personas.md:111`) | C17, C30, C42; unsupported gap |
| 2.4 | Has this official's exact wording on the topic changed between 2015 and 2024? (`docs/congress-explorer-personas.md:115`) | C15, C30, C42; unsupported gap |
| 2.5 | Does the archived PDF match what is on the committee's site today? (`docs/congress-explorer-personas.md:119`) | C42; unsupported gap |
| 2.6 | Is this "hearing date" the meeting date or the document date? (`docs/congress-explorer-personas.md:123`) | C12, C28, C43; plan only |
| 2.7 | Did that dollar figure come from the CBO estimate or a member's opening statement? (`docs/congress-explorer-personas.md:127`) | C15, C32, C37; external detail unverified |
| 2.8 | Is the quote present in the PDF edition but absent from the HTML alternate? (`docs/congress-explorer-personas.md:131`) | C03, C15; plan only |
| 2.9 | Confirm the full hearing title, chamber, Congress, and session for my correction notice. (`docs/congress-explorer-personas.md:135`) | C17, C28, C43; plan only |
| 2.10 | This source is image-only — can the tool verify it at all? (`docs/congress-explorer-personas.md:139`) | C15, C42; unsupported gap |
| 3.1 | Hearing counts by committee per Congress, 112th–119th — normalized by roster size. (`docs/congress-explorer-personas.md:150`) | C18, C29, C36, C41; plan only |
| 3.2 | Distribution of witness appearances by organization over time — which orgs dominate? (`docs/congress-explorer-personas.md:155`) | C18, C30, C41; plan only |
| 3.3 | Are bills with more subject-key hearings more likely to reach a floor vote? (`docs/congress-explorer-personas.md:159`) | C18, C32, C37, C41; external detail unverified |
| 3.4 | How does publication lag (`document_date` vs `first_captured`) vary across committees? (`docs/congress-explorer-personas.md:164`) | C18, C43; plan only |
| 3.5 | What fraction of captured URLs eventually die, by year of first capture? (`docs/congress-explorer-personas.md:168`) | C18, C41; plan only |
| 3.6 | What share of marked-up bills had a printed hearing first? (`docs/congress-explorer-personas.md:175`) | C05, C18, C32; plan only |
| 3.7 | In the 119th, what is the lag from nomination referral to hearing? (`docs/congress-explorer-personas.md:178`) | C32, C37, C43; external detail unverified |
| 3.8 | Recording-coverage bias: which meeting types get archived to committee channels? (`docs/congress-explorer-personas.md:181`) | C18, C35, C36; plan only |
| 3.9 | Can I study witness gender over time here? (`docs/congress-explorer-personas.md:185`) | C42; unsupported gap |
| 3.10 | Pin every figure in my table to this `release_id` and emit the exact SQL as an appendix. (`docs/congress-explorer-personas.md:189`) | C07, C18; plan only |
| 4.1 | Build the dossier for Thursday's hearing: witnesses, their documents, recordings. (`docs/congress-explorer-personas.md:202`) | C05, C28; plan only |
| 4.2 | Has each witness testified before? Pull every prior transcript. (`docs/congress-explorer-personas.md:206`) | C05, C15, C30, C42; unsupported gap |
| 4.3 | What documents did each of them submit at their last appearance? (`docs/congress-explorer-personas.md:210`) | C13, C17, C30; plan only |
| 4.4 | Which of our subcommittee members also sit on committees hearing this bill? (`docs/congress-explorer-personas.md:214`) | C05, C18, C29, C31; plan only |
| 4.5 | What did the minority side ask this same witness last time? (`docs/congress-explorer-personas.md:218`) | C15, C42; unsupported gap |
| 4.6 | Summarize every hearing on this bill across both chambers. (`docs/congress-explorer-personas.md:221`) | C05, C15, C32; plan only |
| 4.7 | Which related bills got hearings in prior Congresses and died — where? (`docs/congress-explorer-personas.md:225`) | C32, C37; external detail unverified |
| 4.8 | Does our 2019 field hearing have a recording, and is there a caption track? (`docs/congress-explorer-personas.md:229`) | C28, C35; plan only |
| 4.9 | Current roster with ranks, titles, and party. (`docs/congress-explorer-personas.md:233`) | C05, C29; plan only |
| 4.10 | Find committee-stage records on this bill number from earlier Congresses. (`docs/congress-explorer-personas.md:235`) | C18, C32, C54; plan only |
| 5.1 | Every hearing transcript for nominee X, plus the committee's votes. (`docs/congress-explorer-personas.md:248`) | C05, C32, C37; external detail unverified |
| 5.2 | All floor amendments sponsored by this member in the 119th. (`docs/congress-explorer-personas.md:252`) | C32, C37; external detail unverified |
| 5.3 | This member's GovTrack, OpenSecrets, and FEC IDs so I can pull the money elsewhere. (`docs/congress-explorer-personas.md:255`) | C31; plan only |
| 5.4 | Every document this member is tagged in — statements, letters, submissions. (`docs/congress-explorer-personas.md:260`) | C17, C31; plan only |
| 5.5 | Witnesses from organization Y across all committees: which bills were they supporting? (`docs/congress-explorer-personas.md:264`) | C18, C30, C41; plan only |
| 5.6 | Give me the `vote_id`s for this bill's roll calls so I can pull member ballots from SpicyRegs. (`docs/congress-explorer-personas.md:268`) | C32, C37; external detail unverified |
| 5.7 | Nominations heard in committee but never scheduled for floor action, 119th. (`docs/congress-explorer-personas.md:272`) | C18, C32, C37; external detail unverified |
| 5.8 | Did this nominee author any document that was later removed from a committee site? (`docs/congress-explorer-personas.md:276`) | C12, C30, C42; unsupported gap |
| 5.9 | Is there any attendance record for this member's subcommittees? (`docs/congress-explorer-personas.md:280`) | C42; unsupported gap |
| 5.10 | Everything this member said at hearings on this topic in prior Congresses. (`docs/congress-explorer-personas.md:283`) | C15, C31, C42; unsupported gap |
| 6.1 | All hearings where this bill's key language was debated — include transcripts. (`docs/congress-explorer-personas.md:295`) | C05, C15, C32; plan only |
| 6.2 | Which committee reported the bill, and what do its markup records show? (`docs/congress-explorer-personas.md:299`) | C32, C54; plan only |
| 6.3 | Every CBO cost estimate across the bill's versions. (`docs/congress-explorer-personas.md:303`) | C32, C37; external detail unverified |
| 6.4 | GovInfo `package_id`s for the printed hearings so I cite the official record. (`docs/congress-explorer-personas.md:306`) | C12, C32; plan only |
| 6.5 | Did the sponsor explain this provision's purpose at hearing? (`docs/congress-explorer-personas.md:309`) | C15, C31, C42; unsupported gap |
| 6.6 | Committee-stage amendments on this bill, 119th. (`docs/congress-explorer-personas.md:313`) | C32, C54; plan only |
| 6.7 | Prior-Congress versions of this bill and their hearing trails. (`docs/congress-explorer-personas.md:316`) | C32, C37; external detail unverified |
| 6.8 | Full-text search the entire Congress's hearing bodies for this statutory term. (`docs/congress-explorer-personas.md:320`) | C15, C42; unsupported gap |
| 6.9 | Nomination hearings that discussed this agency's authority. (`docs/congress-explorer-personas.md:324`) | C15, C32; plan only |
| 6.10 | Exact page cites for the three quotes going into the brief. (`docs/congress-explorer-personas.md:326`) | C15, C43; plan only |
| 7.1 | Pipeline status for our five bills: hearings, amendments, votes, CBO. (`docs/congress-explorer-personas.md:338`) | C32, C37; external detail unverified |
| 7.2 | Which hearings touched our bills without tagging them? (`docs/congress-explorer-personas.md:341`) | C11, C15, C42; unsupported gap |
| 7.3 | Cosponsor counts for our bills as of this release. (`docs/congress-explorer-personas.md:345`) | C32, C37; external detail unverified |
| 7.4 | Scheduled hearings on our topic that have published nothing yet. (`docs/congress-explorer-personas.md:349`) | C11, C28, C36; plan only |
| 7.5 | Who testified against our bill, representing whom? (`docs/congress-explorer-personas.md:352`) | C15, C30, C42; unsupported gap |
| 7.6 | Which committees are demonstrably dead-ends for our issue? (`docs/congress-explorer-personas.md:355`) | C18, C36, C41; plan only |
| 7.7 | Watch our issue's document set for removals and swaps. (`docs/congress-explorer-personas.md:358`) | C26, C42; unsupported gap |
| 7.8 | Our founder testified twice in 2023 — find both appearances and the videos. (`docs/congress-explorer-personas.md:361`) | C15, C30, C42; unsupported gap |
| 7.9 | Committee-stage activity on our bill this month. (`docs/congress-explorer-personas.md:365`) | C32, C54; plan only |
| 7.10 | Draft the one-page stakeholder update with inline citations. (`docs/congress-explorer-personas.md:368`) | C07, C12, C15; plan only |
| 8.1 | All surviving recordings for that hearing, with caption tracks. (`docs/congress-explorer-personas.md:379`) | C28, C34, C35; plan only |
| 8.2 | Which hearings on this topic have video, audio-only, or nothing? (`docs/congress-explorer-personas.md:383`) | C18, C35, C36; plan only |
| 8.3 | Find the timestamp where the CEO says "[phrase]" — search the caption track. (`docs/congress-explorer-personas.md:387`) | C15, C48, C42; unsupported gap |
| 8.4 | Which committee channels posted this event, and what are the original URLs? (`docs/congress-explorer-personas.md:391`) | C18, C35, C46; plan only |
| 8.5 | Videos posted by committee channels but never matched to a hearing. (`docs/congress-explorer-personas.md:395`) | C05, C16, C35; plan only |
| 8.6 | Duration and availability of every clip for the edit log. (`docs/congress-explorer-personas.md:400`) | C16, C46; plan only |
| 8.7 | Witness statements from that hearing to intercut with the footage. (`docs/congress-explorer-personas.md:403`) | C17, C28, C30; plan only |
| 8.8 | Every prior appearance of the whistleblower before 2020. (`docs/congress-explorer-personas.md:406`) | C30, C42; unsupported gap |
| 8.9 | What exists for hearings before 2011? (`docs/congress-explorer-personas.md:410`) | C36, C41; plan only |
| 8.10 | Provenance for licensing: the original posting URL and match basis for each recording. (`docs/congress-explorer-personas.md:415`) | C13, C35; plan only |
| 9.1 | A patron's link is dead — do we hold an archived copy of that URL? (`docs/congress-explorer-personas.md:428`) | C24, C34; plan only |
| 9.2 | All formats and editions of this printed hearing. (`docs/congress-explorer-personas.md:432`) | C03, C25, C34; plan only |
| 9.3 | Is this document genuinely absent, or does the table not exist for that era? (`docs/congress-explorer-personas.md:436`) | C10, C33, C36, C44; plan only |
| 9.4 | The GovInfo package for this hearing, please. (`docs/congress-explorer-personas.md:441`) | C12, C32; plan only |
| 9.5 | Verify the Congress and session from the document itself, not the catalog. (`docs/congress-explorer-personas.md:444`) | C15, C43; plan only |
| 9.6 | Are any of these recovered substitutes the true original? (`docs/congress-explorer-personas.md:448`) | C13; plan only |
| 9.7 | What is actually here from before 1901? (`docs/congress-explorer-personas.md:452`) | C36, C41, C43; plan only |
| 9.8 | Find hearings by committee and date range only — no bill number. (`docs/congress-explorer-personas.md:456`) | C18, C27, C28; plan only |
| 9.9 | Crosswalk this historical member to Wikidata for the patron's project. (`docs/congress-explorer-personas.md:459`) | C31; plan only |
| 9.10 | A stable citation for this record, including the release it came from. (`docs/congress-explorer-personas.md:463`) | C07, C12; plan only |
| 10.1 | What tables, columns, and entity keys does this release publish? (`docs/congress-explorer-personas.md:474`) | C01, C10; plan only |
| 10.2 | Which coverage gaps should my UI badge as "unavailable"? (`docs/congress-explorer-personas.md:478`) | C10, C33, C36; plan only |
| 10.3 | What do the published relationships say about joining witnesses to meetings? (`docs/congress-explorer-personas.md:483`) | C04, C10, C17; plan only |
| 10.4 | Write and run "hearings per committee per month" — what does the SQL cost? (`docs/congress-explorer-personas.md:488`) | C05, C18, C41; plan only |
| 10.5 | Which recipes are available that I could surface as one-click views? (`docs/congress-explorer-personas.md:493`) | C05, C10; plan only |
| 10.6 | Row counts per table for my bundle-size budget. (`docs/congress-explorer-personas.md:496`) | C10, C23; plan only |
| 10.7 | What changed between the release I shipped and `e4538f00…`? (`docs/congress-explorer-personas.md:499`) | C07, C09, C26; plan only |
| 10.8 | Which rows are hidden, and does my site need to exclude them by default? (`docs/congress-explorer-personas.md:502`) | C11, C12; plan only |
| 10.9 | Which upstream SpicyRegs tables could I join by ID? (`docs/congress-explorer-personas.md:506`) | C37; external detail unverified |
| 10.10 | What error does a user see when a row busts the 128 KiB response cap? (`docs/congress-explorer-personas.md:510`) | C18, C20; plan only |

Open required scope remains: authentic current fields and retained source history; full news schema/relationships/releases; complete current Committee Explorer schemas/readers; YouTube captions/report parity; actual Sheet formulas and CPI update/error policy; remaining console/module/report routes; known XML/date/coverage defects. Old reader-format compatibility is explicitly retired by the user's greenfield decision. Full-scope acceptance remains unverified.



## Review corrections and still-required full-scope census

The retired surface is new JSON export, not the Committee Explorer workflow. `.github/workflows/publish-explorer.yml:5-22` still declares push, completed collection-run and manual triggers. It restores state (:89), exports retained inputs as Parquet (:95/:123), packages and verifies browser files (:139), packs state (:147), saves IDs/history/receipts/browser assets through save-pipeline-data.sh (:154), and dispatches Pages with exact code/pipeline revisions (:161). Current remote enablement was not checked. Replacement acceptance must follow each declared caller and each application visibility boundary; no workflow is retired by a transitional label or unmounted old UI.

C45 preserves new Parquet export and explicit new-JSON refusal. Baseline `load_previous` (:178) also reads historical JSON partitions and migrates issue history; that is baseline source evidence, not a required old-format decoder in the greenfield stack. Retained raw source evidence and issue history still need a supported current-format path. Baseline `test_missing_receipt_rebuilds_and_json_reuse_is_rejected` (:134) asserts refusal only.

C54 now binds four specific unclosed branches to source, assertion-level current-test scope and decisive independent procedures in consumer-capabilities.json: Congress-specific committee list/detail history, all-history House website discovery/targeted retry/offline reparse, House XML/witness/page fallback, and Senate live/archive caption acquisition. These are maintained journeys; storing final files is not enough to prove their source decisions or resume semantics. Their authentic-input populations remain unverified.

| Open denominator | Required owner and closure evidence |
| --- | --- |
| Remaining source/console/module/report callers | Acquisition/domain owner: enumerate every CLI and scheduled/module invocation through output schema and actual consumer; assign preserved/refused/retired/unavailable disposition. House/Senate/GPO/inventory/transcribe, house-naming and committee schema generators still need complete output-field/branch/window/history maps beyond the four C54 subcases. A list of names is insufficient. |
| Committee current-format distribution | Consumer and publication owner: enumerate all six Parquet family schemas, source shards, query metadata/pages, CURRENT/manifest, issue/source history, pack/unpack, browser filtering/budgets, snapshot saving and exact Pages revision dispatch; bind authentic retained output and fresh-process failure/readback procedures. Retire old consumer-format paths; preserve raw evidence/history and new-JSON refusal. |
| News full schema/lifetime | News domain owner: resolve every nested definition/foreign-key/cardinality path across twelve content tables plus releases, bridge and internal materialized stages; bind authentic release snapshots, selected-zero/pending/retraction/correction/rights-expiry cases and raw URI/hash custody. No shared merge/check_corpus helper counts as independent semantic proof. |
| YouTube/caption/report | YouTube/domain consumer owner: retained cache schema/unknown-field/duplicate/timestamp/availability/caption receipts; authentic report-to-cache and browser dashboard parity; dedicated English caption command receipts/tracks/tests separate from Senate captions. |
| CPI/Sheets | Inflation domain owner: inspect actual deployed named ranges/formulas, freeze source response/manual cohorts and map every source/unit/column/update case; decide required-source/freshness/all-down outcomes and partial-year replacement policy before independent cell/value acceptance. |
| Current archive and source-history evidence | Model/consumer owner: bind authentic current-source additions absent from e145, complete table membership/accepted custody, multiple versions and retired-key history. Retained old releases remain baseline evidence; new readers need not decode their old controls. |
| Qualification and activation | Native/runtime and application publication owners: name exact nested/native/table-operation profile, six SQL-suite evidence bindings, browser/MCP representation checks, durable adapter invocation and process/host-loss adoption, plus each product's selected-result/commit/checkpoint/Pages/CSV boundary. Catalog compilation alone proves none of these. |

All capabilities remain unverified. These are owned closure requirements, not a claim the preparation or replacement is complete.

## Current ownership and remaining producer adoption

The authored declarations and 16 SQL recipes live in model/ddk. MCP and browser discovery now read admitted public catalog data directly, including typed Open Data Contract Standard (ODCS) fields, standard identities, full relationship/recipe IDs, JSON Schema parameters and parameterOrder. Their retired schema decoder and the provisional archive_definitions reverse converter are removed. Incidental JSON ordering does not define domain meaning. No compatibility schema, legacyKeys map or broad definition hash should be reintroduced.

The incumbent native producer still uses archive_schema.py and release-schema.json, including its policy-bound capture-profile-v2 extension. This active path must keep its guarantees until the execution owner can adopt the admitted definitions, nested native output mapping and exact-candidate evidence together. The parent's archive_catalog.py reads admitted local definitions and preserves domain native SQL checks without registry conversion. It is not yet the complete execution path. ArchiveRelationshipProfileV1 supplies explicit maintained relationship semantics; static semantic checking does not establish observed native uniqueness, foreign-key data coverage or field-ID equality.

The sole native job builder and post-result finalizer remain visible seams. The intended execution owner retains one admitted local definition result before work, binds actual protected native outputs and required evidence, then delivers only exact public passed CatalogResult.artifacts. Resume must use retained inputs and finalization controls rather than reread current definitions. Required unsupported checks remain unknown; incomplete metadata produces no publishable artifacts. The schema.json emission, incumbent registry and its extra-field registry retire in the same producer-owner change, after supported behavior is proven. No second journal or controller is needed.

Keep computation dependencies distinct from catalog refresh: metadata-only recipe/description changes refresh catalog controls; changed quality requirements may requalify retained values; computation changes invalidate affected phases. Native lake schema/field IDs, domain SQL and parser-version authority stay in their maintained owners until their exact successor supports the same guarantees. News and committee domain models remain named full-scope work, not silently covered by the archive declarations.

Independent frozen metadata assertions live in packages/viewer_publication/tests/test_ddk_definitions.py; its original 254-field oracle remains inert test evidence, with three explicit current capture fields and deliberate removal of old-reader prose. MCP test_relationships.py executes every published recipe; test_catalog.py checks genuine public assembly, metadata tampering and companion/definition refusal. test_reader.py and site archive-unit.test.ts cover current field presence, nullable values, association scope and absent/empty/unavailable distinctions. The new nonnative test_archive_reader.py::test_current_reader_requires_current_fields_and_preserves_nulls uses real public controls and seven hand-worked physical rows to check browser refusal and nullable values. These focused procedures are not full native replacement acceptance. The latest field/UI cleanup is prepared for central execution; no result is claimed here.
