---
id: ct-n5ec
status: in_progress
deps: []
links: []
created: 2026-11-10T00:20:04Z
type: bug
priority: 0
assignee: mikewolfd
tags: [nightly, model, engine]
---
# Nightly base_normalized exhausts the query pool: four trailing LEFT JOINs build on the document row; engine slice guard misses list columns

Nightly 20261109T224443 failed at model step 172 base_normalized: charged 9.26 GiB of a 12 GiB pool for about 1.2 GiB real. Findings: .cache/archive-release/investigations/nightly-20261109T224443-base-normalized-memory/findings.md. Owner chose (2026-11-10, questions tool) SQL and engine together: move the four trailing LEFT JOINs in model/sql/document-normalized.sql into the RIGHT JOIN nest and guard it in the join audit test; fix docspec-rs sliced_batch_bytes for nested columns, rebuild and re-pin. Also decide and record whether the fallback to the remote runtime limits (24 GiB, above the 14 GB watchdog) is intended: publish-model.json names a runtime file that does not exist.

## Acceptance Criteria

Join audit test covers base_normalized. Old and new step output byte-identical ordered by doc_key. Engine test shows a sliced List build input is no longer charged per slice. Re-pinned engine passes the full lanes. A nightly passes base_normalized.


## Notes

**2026-11-10T00:45:14Z**

SQL half done on branch claude/ct-base-normalized-joins (local commits, not pushed, not merged).

Done
- e8c4b8a5: the four trailing LEFT JOINs in model/sql/document-normalized.sql (rt, x, fc, bd) are now the four outer layers of the RIGHT JOIN nest, same join order, same single ON condition each. Select list unchanged. The fixture plan shows nine Right joins on component, each built on its one small relation.
- 34a425bc: in model/sql/document-recovery-normalized.sql the two candidate subqueries name the distinct recovered-body set first, so the join no longer builds on captures (4.17M rows in the failed nightly) or on source_annotation_pages.
- 9edeb7c9: test_phase1_model_join_audit.py refuses any Left, Right or Full join in base_normalized whose build input scans document_bodies or document_identities. It failed on the old SQL and passes on the new.
- 7807109d: test_phase1_model_repeat_cost.py tracks every reader of the submitted job with a LEFT or FULL join whose left input is estimated at 100,000 rows or more (OUTER_BUILD_TRACKED, exact list). It flags the old base_normalized (4 joins, 349K rows) and not the new.
- No pin moved. No tracked file holds the digest of either SQL file; the model profile hashes them at build time, so profile_sha256 changes, and a retained model intent from before the change is refused as "Model definitions changed", as intended.

Not done
- Byte identity at full size. Prepared, not run: scratch-sqlfix/sf-proof-dryrun-4 holds the failed nightly's job cut before base_normalized, with the new and old SQL as two steps, both exported ORDER BY doc_key. It needs a runtime that can read the five pinned lake tables in the raw bucket (the Mac remote runtime; 24 GiB, 2 threads, the limits the nightly ran under; the 14 GiB local limits allow only 6 GiB of scratch). About 8 to 9 minutes, about 10.5 GiB RSS. Rebuild it with sf-make-proof-job.py if the SQL changes again.
- Row order of base_normalized changes. Of its five direct readers only model/sql/page-descriptions.sql:42 is order-sensitive (row_number ordered by format rank and path; a tie needs two descriptions at one path of one body, not checked on data). Readers further down were not audited one by one.
- Engine fix, re-pin, full lanes, a nightly, and the runtime-limits decision are unchanged from the ticket body.

Known offenders of the same shape (not rewritten here; ranked by estimated build rows; estimates come from an empty plan and the 2026-11-04 row fixture, "unmeasured" means the step is missing from that fixture and takes its largest input's rows; the line is the file's first LEFT JOIN, not necessarily the flagged one)

| reader | where (first LEFT JOIN) | joins | est. build rows, set by | cols |
|---|---|---|---|---|
| recovery_candidates | model/sql/provenance-recovery-candidates.sql:9 | 3 | 4.1M, captures | 16 |
| meeting_detail_evidence | model/sql/meeting-detail-evidence.sql:33 | 2 | 4.1M, congress_gov_routes (unmeasured) | 16 |
| meeting_detail_observations | model/sql/meeting-detail-observations.sql:21 | 3 | 4.1M, meeting_detail_evidence (unmeasured) | 15 |
| url_state_lines | packages/viewer_publication/src/viewer_publication/archive_url_state.py:31 | 2 | 4.1M, captures | 11 |
| entity_profile_completeness (query) | packages/viewer_publication/src/viewer_publication/archive_model_profile.py:182 | 3 | 4.1M, captures | 5 |
| recording_tracks | model/sql/recording-tracks.sql:12 | 1 | 2.8M, recording_track_candidates | 11 |
| source_addresses | model/sql/source-addresses.sql:4 | 1 | 2.1M, source_files | 3 |
| source_annotations | model/sql/source-annotations-final.sql:39 | 1 | 2.1M, source_files | 2 |
| document_identities | model/sql/document-identities.sql:17 | 2 | 2.1M, document_members | 4 |
| document_metadata | model/sql/document-metadata.sql:18 | 1 | 2.1M, document_members | 10 |
| component_meeting_links | model/sql/component-meeting-links.sql:5 | 4 | 2.0M, document_metadata | 5 |
| review_overrides | model/sql/reviews-review-overrides.sql:5 | 3 | 1.8M, document_identities | 5 |
| model_url_keys | model/sql/url-keys.sql:22 | 1 | 1.7M, url_inputs | 1 |
| page_dates | model/sql/page-dates.sql:5 | 1 | 1.4M, page_metadata_values (unmeasured) | 5 |
| document_page_metadata | model/sql/document-page-metadata.sql:19 | 7 | 1.4M, html_metadata_readings (unmeasured) | 19 |
| source_filename_readings | model/sql/source-annotations-filename.sql:99 | 1 | 1.4M, filename_readings | 27 |
| source_url_keys | model/sql/url-keys.sql:22 | 1 | 1.3M, source_url_inputs | 1 |
| document_packages | model/sql/document-packages.sql:44 | 2 | 569K, saved_files | 3 |
| retired_links_export | model/sql/retired-links.sql:46 | 12 | 440K, prior_links | 6 |
| bills_export | model/sql/entity-bills.sql:93 | 7 | 422K, spicy_congress_bills | 19 |
| meetings_export | model/sql/entity-meetings.sql:33 | 9 | 374K, ordered | 31 |
| page_descriptions | model/sql/page-descriptions.sql:36 | 4 | 356K, base_normalized | 8 |
| document_page_metadata_entries | model/sql/document-page-metadata-entries.sql:17 | 5 | 356K, page_metadata_documents (unmeasured) | 15 |
| source_members.parquet (export) | packages/viewer_publication/src/viewer_publication/archive_model.py:1330 | 1 | 356K, ordered | 6 |
| model_invariants (query) | packages/viewer_publication/src/viewer_publication/archive_model.py:926 | 2 | 356K, ordered | 2 |
| blank_filename_reasons (query) | packages/viewer_publication/src/viewer_publication/archive_model.py:573 | 1 | 356K, ordered | 2 |
| source_annotation_pages | model/sql/source-annotations-pages.sql:9 | 2 | 313K, page_facts | 5 |
| document_witness_keys | model/sql/document-witness-keys.sql:24 | 2 | 205K, document_witness_raw_matches | 3 |
| witness_key_map | model/sql/witness-key-map.sql:70 | 1 | 177K, witness_key_priors (unmeasured) | 3 |
| relationship_invariants (query) | packages/viewer_publication/src/viewer_publication/archive_schema.py:300 | 1 | 177K, witness_key_map_export (unmeasured) | 2 |
| witness_key_current | model/sql/witness-key-current.sql:26 | 1 | 173K, appearance_records_resolved | 15 |
| document_witness_url_matches | model/sql/document-witness-url-matches.sql:23 | 1 | 173K, appearance_records_resolved | 4 |
| document_witness_meeting_witnesses | model/sql/document-witness-meeting-witnesses.sql:8 | 1 | 173K, appearance_records_resolved | 5 |
| witnesses_export | packages/viewer_publication/src/viewer_publication/archive_model.py:847 | 1 | 173K, appearance_records_resolved | 20 |
| coverage (query) | packages/viewer_publication/src/viewer_publication/archive_format.py:347 | 3 | 173K, witnesses_export | 7 |

Also seen, not tracked: three RIGHT joins build on a large joined relation (source_url_normalized, source_annotation_publisher, source_input), and base_normalized's five inner joins build on the growing document row because the planner reorders inner joins.

## 2026-11-10 proof, lanes, review (session congress-1)

Commit hashes cited in the note above are from before the move onto dc5782dd and are on no
branch. Current commits: 02c4656f guard, 9946246a join order, 2ae32ba5 recovery subqueries,
2236b7b6 whole-model lint, b441f29d description tie-break.

- Byte identity, full size: old and new `base_normalized` export the same bytes, sha256
  e0e0d6fe406b4556f3587a441fae0aab549b9a5ad0fa833065ab778c48458ece, 357,443 rows and distinct
  doc_keys each, on the failed nightly's job (83be9f32, 147 ancestor steps). 465 s, peak 9.00 GiB
  RSS. New SQL's largest join build 224.0 MB (EXPLAIN ANALYZE, 25 joins). The old SQL also
  completed here, as it did on 14 earlier runs: the failure is marginal. Evidence:
  `.cache/archive-release/investigations/nightly-20261109T224443-base-normalized-memory/scratch-sqlfix/sf-proof-dryrun-4/`.
  It cannot see steps after `base_normalized`, and it predates b441f29d.
- b441f29d adds the value as the last key of the description pick (`page-descriptions.sql`). No
  tie was shown or ruled out on data; count `(body_sha, path)` repeats in `page_metadata_values`
  on the next finished candidate. Reviewer: `page-dates.sql:3`,
  `document-page-metadata-entries.sql:42` and `document-page-metadata.sql:39,47` have the same
  theoretical tie; `archive_format.py:168` orders every later reader by unique `doc_key`.
- Lanes on b441f29d: production-offline six shards, all `exit 0`, 12,341 passed; storage-loopback
  (full lane) exit 0, 35 passed. Logs: `.cache/archive-release/lanes-ct-n5ec-b441f29d/`.
- Independent review: ship with should-fixes. Rows unchanged (bag comparison, planted wrong
  rewrite caught). Open should-fixes, not done here:
  1. The lint's `NODE` regex (`test_phase1_model_repeat_cost.py:153`) drops plan lines with
     nothing after the colon; parsed fully it finds 129 joins in 38 readers, not 93 in 35, and it
     ignores semi/anti/mark joins. `OUTER_BUILD_TRACKED` is exact only against the lint itself.
  2. The recovery subquery flips (2ae32ba5) have no guard.
- Engine (docspec-rs `fix/nested-slice-bytes`, 0654157, local): mechanism reproduced in a test
  (second join build charged 1.74 GB for 159 MB; 109 MB after). Reviewer: nested-loop join build,
  cross join, round-robin repartition and sort-merge buffers are still charged per slice; better
  to wrap the output of hash joins that emit build rows at the end. The step log's
  `charged_bytes` is the retained result, not peak pool reservation; a per-step peak metric is
  missing. Rebuild, re-pin and full gate follow the release.
- Open: whether the fallback to the remote runtime limits (24 GiB engine limit above the 14 GB
  watchdog; `publish-model.json` names a missing runtime file) is intended.
