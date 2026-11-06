# Congressional native profile: exact integration request

This request makes the archive model's native integration concrete. It preserves the eight existing Iceberg snapshot pins and the whole shared SQL job. It does not claim that the released managed DDK/DocSpec profile can adopt these pins, preserve the nested schema, or recover this job yet. Those parent-owned target semantics remain explicit below.

The parent confirmed the production direction: one DDK component with named
dataset input and output ports contains the complete native `JobSpec` produced
by `plan_prepared_release`. Shared materialized steps, exports and reports stay
in that single job. DDK and DocSpec own transport, exact typed reads, complete
candidate qualification and native recovery. Raw Iceberg selectors retain
`metadata_location`, `table_uuid`, `snapshot` and `schema_id`; no application
adapter invents a `VersionRef` or replaces a snapshot with the latest table.
The exact shared binding API remains under development.

The greenfield output definition now includes the three actual policy-bound
capture fields: 257 physical fields in total. New publication requires explicit
`capture_profile` version 2; an absent policy does not mean eligibility passed.
The original version-1 graph below remains a preserved computation baseline,
not an accepted complete candidate for that current output shape.

The companion [native-profile.json](native-profile.json) contains the exact original selectors, all eight source schemas and their physical IDs, all 251 live step specifications and dependencies, every export setting and SQL report, the planned meeting example, and named unresolved decisions. The JSON is request documentation, not a runnable native request: group/version bindings are deliberately `null` where no native `VersionRef` exists.

Scope is the current checked-in archive publish model at the parent-declared baseline `a06eb64bf3caa4a44e12a89bdd08939323de3092`. Broader acquisition and consumer obligations remain in the existing capability inventories. This work read metadata and rendered declarations only; no native engine, job, test, corpus scan/copy, network request, Git operation, or shared-repository edit occurred.

The parent release record at `/Users/mikewolfd/Work/artifacts/ddk-replacements-20261106/release-status.json`, updated `2026-11-06T10:35:53.437087+00:00`, records `implementationReady=true`. Production cutover remains false. Its qualified DocSpec source is `b1270b2e964becc5844bb6ca95ee5d605c7a3d79`; this checkout still pins `b0342a7368fa1e2c7e957f228c12f74cd1117f65`. Local release qualification is historical parent evidence, not congressional profile acceptance.

## Original native bindings

`model/jobs/publish.json` pins `publish-model.json` with SHA-256 `9f2b4758521b4d790937e04988a7c78274431f4683b7354e52f899baf665b8af`, size 5,085 bytes. That model declares these eight immutable selectors. Every `schema_id` is 0. Every original location retains scheme `s3`, authority `congressional-tech-raw`, catalog `ct-archive-v2`, and namespace `archive_r1b`. The JSON preserves each full `metadata_location` byte for byte.

| Relation | Table UUID | Snapshot | Native version/group |
| --- | --- | ---: | --- |
| `captures` | `01a1a35c-8940-77f2-a48f-c52881d2ccb2` | `3719403341459182653` | Unknown / unknown |
| `readings` | `01a1a35e-550f-79f2-81a2-b7412fd72bc6` | `41537200215124099` | Unknown / unknown |
| `filename_readings` | `01a1ab92-5b30-7580-9721-aa3b70ef1ee3` | `92077548721946488` | Unknown / unknown |
| `meeting_records` | `01a1adb0-549d-7611-b73c-43123b27949b` | `4774524604137558945` | Unknown / unknown |
| `appearance_records` | `01a1adb0-13d1-7bb1-a783-09608e74a3ea` | `8326201294940634343` | Unknown / unknown |
| `video_records` | `01a1a36c-dac3-70d3-94aa-f571c0017da8` | `5595115807617726608` | Unknown / unknown |
| `committee_records` | `01a1adb1-3977-7100-aa7f-878e5389dde9` | `6370388124943983332` | Unknown / unknown |
| `playlist_records` | `01a1adb1-19bb-7421-901b-f03c541a3c01` | `387616457107628486` | Unknown / unknown |

These are source-declared pins, not observed current table heads. This work did not open remote metadata or payloads. The local `model/lake/*.schema.json` files declare the expected schema; they do not independently prove that the remote snapshot has that schema. A protected native admission must check their association.

The incumbent `lake/tables.py:123-135` and `archive_model_job.py:51-71` already preserve exact `metadata_location`, `table_uuid`, `snapshot`, and `schema_id`. The broader native `JobInput` has a `NativeTable` variant. DDK's released calculation profile refuses raw native-table/catalog requests and accepts a different local source-only `VersionRef`; the local managed path also refuses remote objects, inherited bases and computed/related groups. Extending the owning native profile is necessary. Replacing the URI with a local path, deriving a BLAKE3 manifest from the SHA-256/table UUID, or labeling a table as group `source` would fabricate identity.

`captures` keys source occurrences by `(receipt_key, receipt_line, capture_index)`. `readings` keys interpretations by `(body_sha, parser, parser_version)`. The five record tables key `(record_sha, source, parser_version)`. `filename_readings` keys `(filename, source_url, catalog_version)`. Equal content does not collapse occurrences. The configured table writer uses Zstandard level 3, 128 MiB target files, 100,000-row/32 MiB row groups; preserve those declared settings unless a measured, separately accepted change justifies another layout.

The other 43 job inputs comprise 18 policy registries, 12 pinned SpicyRegs tables, parser/compatibility definitions, predecessor link/source/retirement ledgers, provenance, recording decisions and the curated channel directory. `all_inputs` records their owning definitions. The 12 SpicyRegs table pins retain six generation identities and exact path/digest/size/row metadata from `model/jobs/spicy-regs/spicy-regs.json`; no new local native version was created. The five-MiB recording-decision file is pinned by the model but was not opened. Relative worktree paths do not establish custody of retained main-checkout data. The selected predecessor ledger must come from the actual publisher context; it cannot be silently replaced with an empty production ledger.

## Exact meeting schema and physical identity

The meeting source has schema ID 0 and identifier field IDs `[1, 5, 2]`. It contains 61 field/element IDs, including the binary content field `record_sha: fixed[32]`, nested lists, nested structs, required elements and optional collections. The following complete ID map comes from `model/lake/meeting-records.schema.json`; it is a source declaration, not an observed Arrow receipt.

| Physical path | Native ID kind/value | Physical type | Required |
| --- | --- | --- | --- |
| `record_sha` | field `1` | `fixed[32]` | yes |
| `parser_version` | field `2` | `string` | yes |
| `status` | field `3` | `string` | yes |
| `error_type` | field `4` | `string` | no |
| `source` | field `5` | `string` | yes |
| `meetings` | field `6` | `list` | yes |
| `meetings[]` | element `7` | `struct` | yes |
| `meetings[].event_id` | field `8` | `string` | yes |
| `meetings[].chamber` | field `9` | `string` | no |
| `meetings[].congress` | field `10` | `int` | no |
| `meetings[].session` | field `11` | `int` | no |
| `meetings[].updated` | field `12` | `string` | no |
| `meetings[].title` | field `13` | `string` | no |
| `meetings[].meeting_date` | field `14` | `string` | no |
| `meetings[].meeting_type` | field `15` | `string` | no |
| `meetings[].status` | field `16` | `string` | no |
| `meetings[].sittings` | field `17` | `list` | yes |
| `meetings[].sittings[]` | element `18` | `struct` | yes |
| `meetings[].sittings[].start` | field `19` | `string` | no |
| `meetings[].sittings[].end` | field `20` | `string` | no |
| `meetings[].sittings[].room` | field `21` | `string` | no |
| `meetings[].sittings[].building` | field `22` | `string` | no |
| `meetings[].sittings[].address` | field `23` | `string` | no |
| `meetings[].committees` | field `24` | `list` | yes |
| `meetings[].committees[]` | element `25` | `struct` | yes |
| `meetings[].committees[].system_code` | field `26` | `string` | no |
| `meetings[].committees[].name` | field `27` | `string` | no |
| `meetings[].committees[].chamber` | field `28` | `string` | no |
| `meetings[].committees[].role` | field `29` | `string` | no |
| `meetings[].subject_keys` | field `30` | `list` | yes |
| `meetings[].subject_keys[]` | element `31` | `string` | yes |
| `meetings[].transcript_jackets` | field `32` | `list` | yes |
| `meetings[].transcript_jackets[]` | element `33` | `int` | yes |
| `meetings[].videos` | field `34` | `list` | yes |
| `meetings[].videos[]` | element `35` | `struct` | yes |
| `meetings[].videos[].video_key` | field `36` | `string` | no |
| `meetings[].videos[].url` | field `37` | `string` | no |
| `meetings[].videos[].title` | field `38` | `string` | no |
| `meetings[].document_urls` | field `39` | `list` | no |
| `meetings[].document_urls[]` | element `40` | `string` | yes |
| `meetings[].collection_states` | field `41` | `struct` | no |
| `meetings[].collection_states.sittings` | field `42` | `string` | no |
| `meetings[].collection_states.committees` | field `43` | `string` | no |
| `meetings[].collection_states.subject_keys` | field `44` | `string` | no |
| `meetings[].collection_states.transcript_jackets` | field `45` | `string` | no |
| `meetings[].collection_states.videos` | field `46` | `string` | no |
| `meetings[].collection_states.document_urls` | field `47` | `string` | no |
| `meetings[].access` | field `48` | `string` | no |
| `meetings[].access_basis` | field `49` | `string` | no |
| `meetings[].not_held` | field `50` | `boolean` | no |
| `meetings[].title_key` | field `51` | `string` | no |
| `meetings[].reschedule_candidate` | field `52` | `boolean` | no |
| `meetings[].document_references` | field `53` | `list` | no |
| `meetings[].document_references[]` | element `54` | `struct` | yes |
| `meetings[].document_references[].collection` | field `55` | `string` | yes |
| `meetings[].document_references[].ordinal` | field `56` | `int` | yes |
| `meetings[].document_references[].url` | field `57` | `string` | yes |
| `meetings[].document_references[].role` | field `58` | `string` | no |
| `meetings[].document_references[].format` | field `59` | `string` | no |
| `meetings[].document_references[].description` | field `60` | `string` | no |
| `meetings[].document_references[].name` | field `61` | `string` | no |

The adapter must represent container field IDs and element IDs separately. A name/type/position-only match cannot prove this map. `fixed[32]` must read as `FixedSizeBinary(32)` with native ID 1, not a hex string, general binary or arbitrary-width byte array. DDK's present scalar mapping also misses fixed-size binary independently of its missing list/struct support.

The mapping must preserve nullability at every level, duplicate and ordered list elements, a NULL list versus an empty list, an optional NULL struct versus a present struct with NULL members, and empty strings versus NULL scalars. Required lists in this schema cannot become NULL. JSON in the companion example encodes binary only for documentation; the harness must decode exactly 32 bytes before native submission.

## Current shared job and export inventory

The static current-source rendering contains **51 inputs, 251 live relations, 678 named relation dependencies, 40 Parquet outputs and 23 SQL reports**. The relations comprise **235 materialized SQL steps, two connected-component steps and 14 lazy views**. `graph.steps` lists every exact ID, position, SQL/components specification, SQL digest, dependency, direct reader, materialization owner and `release_after` list. `graph.outputs` records every output's exact SQL, order keys, selected columns, dictionary/delta settings, row-group settings and footer bound. These counts describe declarations; they do not measure physical scans, memory or speed.

The inventory renders only the declarations in `archive_model.py`, `archive_format.py` and their maintained helpers. The metadata-only renderer excludes imports, directory creation, native submission and execution/write suffixes. Its prefix follows the current publish model's native-table branch, including playlist selection. It uses the maintained `lake/model_sql.py` DuckDB 1.5.5 syntax-tree reader to compute external relation references with CTE scope; the reader removes the DataFusion `ANTI` lexer token in its parser copy while retaining both join operands. All named dependencies resolve to earlier inputs/steps. The maintained `retire_relations` function removes unused relations and assigns final readers.

No dependency edge is a lexical/regular-expression inference. No SQL was bound or executed against data. Internal CTE expansion, optimizer pushdown, join build sides, physical scans and runtime type support remain unqualified. The predecessor publisher may add inputs/provenance to this checked-in model; that is a distinct exact request. Do not claim this source rendering freezes those later additions.

Native job relations are not managed native groups. The JSON keeps every such group `null`. A retained shared result may become a protected native phase result or a group under a parent-chosen lifecycle operation; the parent must return that actual binding. DDK must not create its own parallel completion database.

These examples show why one native shared job matters:

| Relation | Treatment | Direct named readers, including reports/exports | Meaning of sharing |
| --- | --- | ---: | --- |
| `capture_evidence` | materialized_sql | 8 | Capture facts feed source classification and a private evidence export. |
| `selected_readings` | lazy_view | 5 | One current/compatible parser selection; consumers project their needed columns. |
| `page_facts` | materialized_sql | 8 | Body facts feed links, annotations, meetings, recordings and evidence. |
| `link_inputs` | materialized_sql | 4 | Resolved link paths reuse the same materialized link population. |
| `meetings_resolved` | materialized_sql | 15 | Source selection/merge is shared by relationships, entities, coverage and scheduling. |
| `source_annotations` | materialized_sql | 12 | Display/source facts feed document modeling and several checks. |
| `document_members` | materialized_sql | 16 | One final membership serves identities, metadata, witness joins, lookup and evidence. |
| `ordered` | materialized_sql | 23 | One ordered document population defines list positions and downstream ranges. |
| `details` | materialized_sql | 7 | Detail publication, document-row evidence and key checks read the same result. |
| `recordings_entity` | materialized_sql | 2 | Meetings list caption tracks from the same result that recordings exports. |

`document_witness_url_keys`, `document_witness_chrg_components`, `document_witness_url_matches`, `document_witness_meeting_witnesses`, `document_witness_single_meeting_components` and `document_witness_raw_matches` are explicit materialized steps before `document_witness_keys`. Preserve those boundaries: putting them back into one repeatedly referenced CTE restores the documented fanout problem even if each relation has only one downstream step.

The two connected-component steps are `source_components` and `review_components`, each with declared `node_limit=10_000_000`. Native execution owns their batches and lifetime. The other lazy providers must remain live through their final readers; a source `release_after` list is not permission to remove protected durable data.

The 23 public Parquet outputs are:

| Output | Registered relation(s) read | Export profile and order |
| --- | --- | --- |
| `list.parquet` | `ordered` | `whole`; `filename, document_date, first_captured, doc_key` |
| `detail.parquet` | `details` | `ranged`; `filename, document_date, first_captured, doc_key` |
| `links.parquet` | `links` | `lookup`; `link_key` |
| `urls.parquet` | `url_keys` | `lookup`; `lookup_key, list_row` |
| `sources.parquet` | `source_rows` | `ranged`; `list_row, ordinal` |
| `recoveries.parquet` | `recovery_rows` | `ranged`; `list_row, ordinal` |
| `meetings.parquet` | `meetings_export` | `whole`; `event_id` |
| `witnesses.parquet` | `witnesses_export` | `whole`; `occasion, panel_order, display_order, witness_key` |
| `witness_key_map.parquet` | `witness_key_map_export` | `whole`; `old_key` |
| `recordings.parquet` | `recordings_export` | `whole`; `video_key` |
| `committees.parquet` | `committees_export` | `whole`; `system_code` |
| `members.parquet` | `members_export` | `whole`; `bioguide_id` |
| `rosters.parquet` | `rosters_export` | `whole`; `congress, system_code, rank, bioguide_id` |
| `bills.parquet` | `bills_export` | `whole`; `bill_id` |
| `nominations.parquet` | `nominations_export` | `whole`; `nomination_id` |
| `videos.parquet` | `videos_export` | `whole`; `video_key` |
| `channels.parquet` | `channels_export` | `whole`; `handle` |
| `recording_matches.parquet` | `recording_matches_export` | `whole`; `match_id` |
| `committee_records.parquet` | `committee_records_export` | `whole`; `record_key` |
| `meeting_coverage.parquet` | `meeting_coverage_export` | `whole`; `event_id, aspect` |
| `url_state.parquet` | `url_state_export` | `whole`; `requested_url` |
| `url_variants.parquet` | `url_variants_export` | `whole`; `variant_url, canonical_url` |
| `retired_links.parquet` | `retired_links_export` | `whole`; `link_key` |

The 17 private evidence outputs are:

| Output | Registered relation(s) read |
| --- | --- |
| `document_rows.parquet` | `details` |
| `source_members.parquet` | `capture_source_contexts`, `document_identities`, `document_members`, `ordered` |
| `filename_conflicts.parquet` | `filename_conflicts` |
| `capture_evidence.parquet` | `capture_evidence` |
| `record_roles.parquet` | `record_roles` |
| `capture_sources.parquet` | `capture_sources` |
| `page_facts.parquet` | `page_facts` |
| `valid_rendition_members.parquet` | `valid_rendition_members` |
| `publisher_links.parquet` | `publisher_links` |
| `current_recoveries.parquet` | `current_recoveries`, `remaining_recovery_decisions` |
| `source_filename_readings.parquet` | `source_filename_readings` |
| `source_annotation_publisher.parquet` | `source_annotation_publisher` |
| `source_annotations.parquet` | `source_annotations` |
| `rendition_members.parquet` | `rendition_members` |
| `edition_bodies.parquet` | `edition_bodies` |
| `fingerprint_candidates.parquet` | `fingerprint_candidates` |
| `fingerprints.parquet` | `fingerprints` |

`document_rows.parquet` shares `details` with the public detail export; `source_members.parquet` reads the existing document/source membership. Other evidence files export existing materialized relations. The shared native exporter must preserve exact settings and partial-output evidence. Do not reopen exports to recompute checks already answered by registered relations, and do not run an independent one-output fixture job for every SQL fragment.

After the native outputs and invariant reports succeed, the application builds `schema.json`, `capture_scope.json`, `capture_profile.json` and `manifest.json`. The first three join the release's content file list; `manifest.json` records that list and its content-only identity. Application publication owns external membership and conditional pointer acknowledgment/reconciliation, separately from native candidate selection.

The full Explorer path has seven blocking SQL report families: `invariants`, `model_invariants`, `url_state_invariants`, `profile_completeness`, `entity_profile_completeness`, `relationship_invariants`, plus `explorer_invariants`. The usual six-suite name omits this Explorer-specific family. The remaining 16 reports carry metadata, disposition and diagnostic detail; their exact SQL and dependency membership are in `graph.queries`. A readable table or source-only quality result cannot substitute for the cross-table blocking reports or downstream reader acceptance.

## Minimum parent-owned protected-pin protocol

1. DDK submits the unchanged original table pin, original scheme/authority and expected recursive schema/ID map. Resolving a mutable head is a separate native operation whose returned immutable pin must then enter the request identity.
2. The native catalog owner verifies UUID/snapshot/schema association and protects all exact references before exposing a view. Protection must cover live readers, retained operation recovery and required history. Credentials remain outside pins and evidence.
3. The native owner either reads that pin directly under protection or returns a metadata-only adoption receipt with the **real** `VersionRef` and group plus the unchanged original pin. No local manifest digest/group can be guessed. No export/reimport or corpus copy is needed to establish the binding.
4. The native/DDK mapping returns every physical container/leaf type, requiredness, field ID and element ID. Wrong association, unsupported type, missing protection or incomplete mapping refuses explicitly before selection. Never fall back to latest or a local source-only import.
5. One native job owns the complete declared graph, shared materializations, durable completion identity, update/retry/reconciliation, invariant evidence and guarded native selection. Exact dependency/definition/schema identity decides reuse before payload reads.
6. The application publication owner composes one complete output membership and exact reader evidence, then applies its existing conditional publication/reconciliation semantics. It preserves prior selected/historical readers through interruptions. DDK composes definitions and evidence without another current pointer or retry controller.

`lake/tables.py` statically demonstrates `resolve`, optional `create_namespace`, `create` and guarded `append`. Append re-evaluates its pending-key anti-join and operation identity on catalog conflicts. The source API does not establish arbitrary correction/delete behavior. The requested replacement needs explicit inherited-source and derived-membership semantics rather than treating an append as an update or absence in partial input as a deletion.

## Independently authored meeting acceptance example

`acceptance_example` supplies one complete synthetic native-schema row. It binds the current `house_xml` parser version, carries two meetings, and gives the first meeting **two equal sitting structs**. Both structs have `room=NULL`, `building=''`, equal start times and nullable remaining fields. The first meeting has `document_urls=NULL` and `document_references=NULL`; the second has empty lists and explicit empty collection states. It uses the source schema's physical IDs, not a flattened substitute.

Two separate synthetic capture occurrence keys point to the same 32-byte content value. The native read must retain both occurrences while the content-level meeting record remains keyed by `(record_sha, source, parser_version)`. Expectations use typed multisets in both directions, retain sitting multiplicity/order and distinguish NULL, empty and absent states. Neither producer code nor model SQL may generate the independent expected values. These invented rows establish a planned edge-case proof only; they are not authentic publisher evidence.

The acceptance sequence is explicit: admit/protect A; append B; then correct A through new content A2 and an explicit supersession/selected-occurrence change. A2 gives event `900000002` exactly one document URL, `https://example.invalid/documents/ddk-before-empty.pdf`, and one reference with `collection='meeting_documents'`, `ordinal=1`, that same URL, `role='statement'`, `format='pdf'`, `description='Independently authored document before explicit empty replacement'` and `name='Before empty replacement'`. The JSON records those independently authored values. Other meeting fields and the initial duplicate-sitting/NULL-versus-empty cases remain intact.

Two separate next cases expose stale-list and false-deletion defects. First, explicitly partial input omits both document collections without declaring a complete replacement; the selected meeting must retain A2's exact nonempty URL and reference. Next, an explicit complete replacement supplies `document_urls=[]` and `document_references=[]`; both selected lists must become empty, with no prior URL/reference retained. The latter case requires the preceding nonempty result as its precondition. A planted stale list after explicit empty replacement and a planted cleared list after partial omission must each fail the independent check.

After explicitly retracting B, planned recovery cases interrupt a costly completed phase and lose a selection acknowledgment. A fresh process must reconcile the original request and reuse completed protected work without local Python/worktree/temp state or repeated source import. Historical versions stay readable. Missing retained input needed by unfinished work refuses instead of selecting latest. A separate completed-retry case first selects a later successor, then retries the original completed v2 operation: it must return v2's original historical result and exact output identities without requiring v2 to remain current, rewinding the successor, or recomputing/importing completed work. The successor remains selected. These are planned acceptance expectations, with no native proof claimed.

Before trusting a pass, the independent checker must reject a planted dropped duplicate sitting or wrong room value, confirmed by a reviewer other than its author. Separate native refusal cases swap field IDs 21/22, change element ID 18, change requiredness, substitute the wrong schema ID/UUID/snapshot, or supply a 31-byte hash/string where `fixed[32]` is required. Field-name equality alone cannot accept these cases. The source/derived correction/deletion protocol remains a parent-owned choice; this example specifies the required outcomes without pretending the incumbent guarded append already implements them.

## Retained evidence, scale and missing qualification

The retained November 5 manifest at `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/live-manifest.json` names release `e145d24c389e43e05a0bcb3f71cd1f75ee919a066dfa810f0ba39a16283d4a99`, 23 public Parquet files and three controls. It reports `meetings.parquet` at 18,687 rows/1,908,156 bytes and `detail.parquet` at 356,735 rows/26,880,700 bytes. These are retained selected-release metadata, not fresh remote or payload checks and not counts for today's eight source pins.

The retained `candidate-streaming-repair/model-scratch/job.json` has 242 steps, 40 outputs and 21 reports. Its companion profile has 32 definition hashes differing from this checkout, including the meeting schema, model/format assembly, several SQL rules and reading/parser code. The JSON names every mismatch. This historical job cannot establish the current graph or current-schema coverage; its output/cost evidence remains useful under its original identity.

Named historical measurements remain deliberately separate:

| Retained evidence | Measured population/result | Practical limit |
| --- | --- | --- |
| `investigations/model-step-theory-20261104.md`, §2 C1 | Historical pinned lake: 4,147,132 captures, 1,416,679 readings, 1,379,144 filename readings, 24,431 meeting records; captures 219 MB compressed/1,007 MB uncompressed pages, as reported | Different input generation; does not size today's pins or replacement memory |
| `investigations/model-step-theory-rebuttal-r3.md`, §2(d) | Two baseline physical peaks 11.35/10.88 GiB; witness-aggregation variants 9.98/9.41 GiB; 39 byte-identical outputs; variant elapsed 288/323 s versus baseline run 1 at 225 s | Historical memory improvement, no speedup; current graph differs |
| Same rebuttal, §2(g) | One 4,147,132-row capture-evidence re-export succeeded with 4/13/20 spills; smaller nonspillable merge budgets failed | One export only; no whole-job or replacement-runtime spill qualification |

All investigation paths above are under `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/`. Source graph counts and historical measurements do not establish current input size, largest nested row/group, total process memory, disk coexistence, physical I/O, selective delta work or performance. This turn starts none of those experiments. The parent reported about 8.7 GiB free disk before assignment; that is a constraint report, not a reservation or current remeasurement.

## Application construction seam and pending native acceptance

The application now exposes its complete supported `JobSpec` through one builder. `archive_format.native_release_job(inputs, steps, *, output, scratch, origin, auxiliary=None, capture_scope=None, extra_outputs=(), diagnostics=(), metadata_queries=(), content_files=None, lookup_extra=None, entity_digests=None)` returns `(job, public_schema, blocking_diagnostics)`. It reads small schema definitions, creates no directories, opens no input rows, submits no native work, and leaves the caller's prepared relation list unchanged. `capture_scope` belongs to the later JSON-control finalization; it adds no separate native operation.

`archive_model.plan_prepared_release(prepared, *, output, root=ROOT)` renders the full model through that builder. `build_prepared_release` retains the incumbent execution path. Both call the same sole model assembly function, and `_execute` now obtains its request from the extracted builder. The extraction removes construction from the executor rather than copying it into another adapter. There is no new request data class, phase database, retry controller, selection pointer or assumed managed API.

The focused test `packages/viewer_publication/tests/test_archive_native_request.py` characterizes the full request against this preparation inventory, including all eight native pins, 251 live step specifications and last-reader releases, 40 output specifications/settings and 23 report SQL definitions. It also verifies that invalid SQL, missing relations and duplicate relation names refuse without creating work, and that the incumbent executor submits exactly the same single request. The inventory was captured before extraction: `native-profile.json.source_definitions` preserves those earlier source hashes as comparison evidence, not the identity of the now-refactored source files. The original table pins, schema IDs and graph definitions remain unchanged.

The required runner passed eight tests, including three existing SQL-dependency/lifetime cases: `production-offline (partial: 2 of 496 lane files; not a lane result): exit 0`. Evidence is retained under `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ddk-replacement-20261106/checks-native-request-01/` in `test-runner-02.log` and `junit-02.xml`. An initial host Poppler mismatch stopped preflight; the later runner-argument refusal and first extraction failure remain in the earlier retained logs. The successful run used this checkout's environment, the retained pinned Poppler path and its configured immutable native runtime; no native job ran. Reading-version diagnostics warned about workspace evidence drift while their fixed samples matched; that is limited incumbent evidence, not a replacement qualification or a parser-version decision.

The actual retained-native acceptance route is now concrete up to the shared native operation:

1. Resolve the original input custody through `archive_model_job.load_spec` and `model_arguments`, retaining the exact eight native pins and the actual SpicyRegs/provenance/predecessor members. Use the original selected manifest and its protection owner; no copy/export/reimport establishes adoption. Missing local generation/decision bindings remain N07.
2. After the parent qualifies the successor runtime/client tuple and its protected-pin/group admission, use `prepare_model_inputs` to produce the application's exact prepared inputs, profile and shared admission prefix. This preparation writes small owned input definitions and needs an admitted durable stage directory. It is distinct from the side-effect-free full graph rendering.
3. Pass that prepared state to `plan_prepared_release`. Submit its unchanged `job` through the parent's supported retained native operation under the original operation/request identity. Native execution owns protection, retained expensive completions and recovery. No new shared managed signature is assumed here.
4. Bind the native candidate to the complete output/view membership, all required checks (`invariants` plus returned blocking diagnostics), rule/evaluator identities and completed-read coverage. The application still has its existing native-result, schema, receipt, reader and publisher gates as comparison oracles. A successful source-only read or one group's quality report does not qualify this full job.
5. Compare authenticated current-schema rows independently, then exercise the planned append/correction/empty/partial/delete/cold/historical-retry cases before replacing the old path. Historical e145 metadata and the older retained native jobs do not cover the current added meeting/page/recording fields or all eight current snapshots.

Before accepting a successor tuple, run the maintained native regression entry points under the required watchdog and a root-admitted resource budget: `test_archive_model_job.py::test_model_cli_executes_real_raw_lake_fixture`, `test_archive_job_metadata.py::test_metadata_rows_do_not_change_release_bytes_or_weaken_guards` and `test_phase1_model_lifetimes.py::test_actual_raw_lake_model_releases_every_relation_after_its_last_reader`. Those generated-row regressions protect request execution, release bytes, checks and lifetimes; authentic retained-native acceptance is a separate obligation. None was run for this extraction. Parent-owned operation/view/evidence extensions remain unqualified, and the incumbent controllers remain the comparison path.

## Actual source preparation and declaration handoff

`<main checkout>/.cache/archive-release/ddk-replacement-20261106/whole-job-binding-04/`
retains a later diagnostic capture through the actual `prepare_model_inputs` and
`plan_prepared_release` functions. Use `handoff-corrected.json` and
`schema-artifacts-v2.json`; their earlier reports remain preserved. This is
explicitly unadmitted source preparation, not a native job or release.

The request has 29 JSON Lines inputs, 14 Parquet inputs and eight original native
table pins. All 51 declarations have artifacts: unchanged native Arrow JSON for
JSON Lines, standard Arrow IPC from local Parquet footers, and the original
Iceberg schema JSON for source-declared native tables. No application type
mapper was added. The parent native preparation API must preserve the JSON
Lines provider's source-tracking fields and distinguish declared input schema
identity from the effective relation schema.

The current preparer reads and converts 2,287 retained nomination rows from
`committees_json` to `committee_activities` before native submission. That
preprocessing is recorded; it is not a zero-row schema operation. Fourteen
retained files totaling 49,618,383 unique bytes were verified in place. This is
not total bytes read: the custody owner rehashes them during its checks. The
separately active main descriptor was refused after its bytes changed. The
capture uses this checkout's exact pinned descriptor with explicit, hash-checked
relocations to the retained generation files. It never substitutes latest.

The actual request still has 251 steps, 40 outputs and 23 reports. All export and
report definitions match the earlier frozen-prefix inventory. One step differs:
the actual `selected_readings` includes the bundle-level `readings` compatibility
branch omitted from the earlier prefix fixture. The characterization tests
exercise the supplied frozen prefix and assembly, not current input preparation.
`step-differences.json` records the exact difference.

The application entrypoint refused the checked-in model before input reads.
Seven parser versions and the filename catalog version hash all of `uv.lock`;
the DDK dependency changes therefore change those fingerprints. The bounded
`parser-lock-drift-02/fingerprints.json` experiment reproduced every original pin
with the baseline lock and unchanged producer code. This diagnoses the identity
mechanism, not parser equivalence or table acceptance. No retained pin or row was
restamped. The low-level capture preserves the original declarations and records
the entrypoint refusal explicitly.

`prepare-spec.draft.json` supplies the 51 declarations to the parent native
owner's `urn:docspec:job:schema-only:1` interface. The original handoff and its
`not_run` sidecar remain unchanged. Later experimental execution is recorded
separately below. Remote pin observation/protection, authentic capture-v2 policy,
production predecessor binding, data execution and qualification remain separate
pending obligations.

## Bounded native schema preparation

`<main checkout>/.cache/archive-release/ddk-replacement-20261106/native-schema-probe-02/`
retains one successful schema-only diagnostic against experimental native
`source05`, binary SHA-256
`bb73e8d8f42c88f5d9ef21f43c34233802bcf8253f171972482858a2df407c61`.
The parent authorized this exact diagnostic after a separately retained first
attempt stopped in the macOS dynamic loader. The corrected policy allows system
loader reads while denying the 43 exact local input payload paths, all network
access and writes outside the diagnostic evidence directory.

The unchanged 482,204-byte native job returned `status: inferred`,
`input_admission: not_run` and `execution: not_run`. Its exact ordered membership
matches all 51 input, 251 step, 40 export and 23 report names. PyArrow 25.0.1 decodes
every one of the 287 content-addressed IPC schemas and verifies their SHA-256
values. All 29 JSON Lines providers include `__source_key`, `__source_line` and
`__raw_line`. All 250 field/element IDs, paths, nesting, order and nullability
match the eight original Iceberg declarations; this comparison does not establish
that a remote table actually has the declared schema or independently qualify
every native type mapping.

All seven blocking report schemas contain their exact 222 declared integer
columns and bind the original SQL digests. No report rows or values were read or
computed. All 23 public output column-name sets match the captured descriptive
metadata. `nominations.parquet` places `committee_activities` before `committees`,
whereas the descriptive metadata lists them in the reverse order; neither field
is missing. Native output order remains authoritative. The 17 private exports
remain included in the complete result.

Native wall time was 1.246 seconds. The watchdog recorded 1.9 seconds total,
0.112 GiB peak process-tree RSS and 0.046 GiB peak physical memory, with no admission
wait. Limits were one compute thread, 512 MiB native memory, 64 MiB scratch,
64 MiB metadata, a 265-second child deadline, a 2 GiB observed RSS stop and a
15 GiB free-disk floor. Baseline/end capacity, the watchdog and sampler identities,
the exact sandbox policy, unchanged application pins and unchanged declaration
hashes are retained. The raw result is `native.stdout.json`; `summary.json` and
`schema-inspection.json` record the separate inspection. No native output file
was created. This diagnostic does not change the application runtime pin, resolve
its producer-version refusal, or qualify execution, protection, recovery,
selection or a data candidate.

## Decisions the native parent must return

The JSON assigns these exact unresolved target semantics:

| ID | Decision and owner |
| --- | --- |
| N01 | DocSpec: protected original remote-table read/adoption request and receipt, authority preserved, real version/group returned |
| N02 | DDK/native mapping: recursive physical schema identity, field/element paths, fixed-size binary and wrong-map refusal |
| N03 | DocSpec: durable shared-step completion and managed candidate/group mapping for the full `JobSpec` |
| N04 | DocSpec plus domain owner: explicit append/correction/supersession/delete and history/concurrency semantics |
| N05 | Native quality plus publisher: exact cross-table invariant evidence admission and separate reader/publication acceptance |
| N06 | Parent runtime owner: qualified repository/client/runtime tuple, using immutable configured binary addresses |
| N07 | Congressional integration: original SpicyRegs/decision-file custody and selected predecessor ledger bindings |
| N08 | Acceptance owner: authentic current-schema records, independent expectations and full-generation denominator |

The smallest extension preserves the native job and original table identities, adds the missing protected read/adoption and mapping/lifecycle operations at their owners, and returns concrete evidence for this profile. Implementation and acceptance remain unexecuted here. No shared-runtime change, external publication or production cutover is authorized by these documents.
