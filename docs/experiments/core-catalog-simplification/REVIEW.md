# Review: ordered metadata updates

No blocking findings remain in the reviewed changes. This is a self-review using
`semi-formal-code-review`, not an independent reviewer or a full-corpus runtime
qualification. The scope includes the capture/publication separation already in
the working tree, explicit metadata reuse, and ordered filename enrichment.
Unrelated explorer and document-catalog work is excluded.

## 1. Patch summary

Routine updates add evidence while retaining existing interpretations. Explicit
rebuilds select current rules. Filename enrichment discovers shared facts while
consuming bounded input batches, writes each temporary Parquet batch once, and
then reads those batches into grouping after future aliases are known.

The workflow selects the operation at
`.github/workflows/capture-raw-sources.yml:96`; `raw_sync.run` dispatches it at
`packages/congress_api/src/congress_api/cli/raw_sync.py:184`. The main change is
`write_filename_metadata` at
`packages/congress_api/src/congress_api/retention/document_index.py:2052`.

## 2. Function trace

All source locations below are relative to `packages/congress_api/src/congress_api/`
unless a test/workflow path is stated.

| Function / method | Location | Inputs → outputs | Verified behavior |
| --- | --- | --- | --- |
| `parser` | `cli/raw_sync.py:57` | CLI flags → operation | Capture, update, rebuild and plan flags are mutually exclusive |
| `connect_storage` | `cli/raw_sync.py:138` | Arguments/status reporter → store | Existing credential/client setup is preserved; test store injection stays outside it |
| `run` | `cli/raw_sync.py:184` | Operation/store → summary and optional publication | Capture skips tables; update skips acquisition; rebuild sets repair; failed stages are recorded |
| `capture_sources` | `cli/raw_sync.py:103` | Store/worker → acquisition result | Fetcher and signal handlers leave scope before catalog processing |
| `main` | `cli/document_index.py:20` | Local flags/archive → update result | `--rebuild` and legacy `--repair` reach both raw-archive and standalone-table branches |
| `_rebuild_catalog` | `retention/raw_catalog.py:49` | Saved captures/metadata → unchanged result or new pair | Capture-prefix integrity still gates reuse; code fingerprints do not; explicit repair prevents reuse |
| `DiskItems.__iter__`, `DiskValues.__iter__` | `retention/catalog_staging.py:13` | Indexed mapping → reiterable values | Ordered SQL scans avoid per-key reads; views can be iterated again |
| `DiskMap.get/items/values` | `retention/catalog_staging.py:55` | Keys/mapping → values/views | `get` uses one lookup and does not create a default entry |
| `DiskRows.items/batches` | `retention/catalog_staging.py:179` | Staged rows → detached batches | Reads do not write; explicit write batches save only changed payloads |
| `ParquetRows` construction, `_write`, `_flush`, `append` | `retention/catalog_staging.py:196` | Rows/schema function → bounded immutable files | A batch is written once; unfinished files remain in disposable staging |
| `ParquetRows.batches/__iter__` | `retention/catalog_staging.py:228` | Temporary Parquet → batches | Uses bounded iteration and closes readers; Arrow null padding in occurrences is removed |
| `write_filename_metadata` / `previous_batches` | `retention/document_index.py:2052` | Source iterator/prior table → pair statistics | Prior name/body results share one projected scan; caller dictionaries are copied before enrichment |
| `interpret`, `inspect_body`, discovery loop | `retention/document_index.py:2143` | Filename/body references → shared facts | Metadata-only runs perform no body reads; missing/oversized bodies retain existing refusal behavior |
| `finalized_rows`, `output_schema` | `retention/document_index.py:2213` | Completed discovery → final rows/schema | Later facts apply to earlier rows; columns are finalized after the stream is consumed; caches are released before combination |
| `write_document_indexes` | `retention/document_index.py:549` | Rows/schema or schema function → paired tables | Delegates to disposable grouping state and closes owned state |
| `write_grouped_indexes` / `normalize` / `signature` | `retention/catalog_staging.py:248` | Current/prior components → reused or rebuilt groups | Reuse requires matching evidence and component membership, not matching code hashes; derived family and null struct padding do not invalidate it |
| `_refresh_source_metadata` | `retention/document_index.py:1781` | Retained source context → refreshed pair | Existing mutations now use explicit write batches; legacy source refresh semantics remain covered |
| `refresh_filename_metadata` | `retention/document_index.py:2322` | Standalone table/repair flag → new generation | Explicit repair controls filename/group reuse without source acquisition |
| `enrich_sources`, `enrich_document_covers` | `retention/document_evidence.py:257`, `:373` | Rows and shared facts → evidence fields | Lookup data is available before final enrichment; response failures remain capture-specific |
| `evidence_fingerprint` | `retention/document_evidence.py:35` | Reader code → provenance hash | Still records reader identity; no longer promises automatic cache invalidation |
| `publish_catalog` | `retention/catalog_publication.py:91` | Validated files/prior selection → selected generation | Validates references, uploads immutable pair, then conditionally selects it |

## 3. Data flow and invariants

- `cached` and `body_cache` are indexed facts, created before discovery, filled
  from prior interpretations and new inputs, consumed during final enrichment,
  then cleared (`document_index.py:2101-2238`). Code changes alone do not clear
  them. Explicit rebuild with body inspection does not load old body results.
- Source input rows are copied before mutation (`document_index.py:2171`). They
  enter the temporary Parquet stream once after initial discovery. Finalization
  starts only after that stream is complete (`document_index.py:2197-2217`).
- Shared URL/body facts must survive until finalization so a late alias can
  enrich an earlier row. The across-batch XML fixture tests this dependency.
- The schema callback runs only after all current rows enter grouping
  (`catalog_staging.py:355`). Newly discovered fields therefore reach both
  output tables, including fields learned during finalization.
- Component reuse compares normalized evidence, prior membership count and a
  paired catalog ID (`catalog_staging.py:297-320,449-468`). Removing or adding a
  bridge recomputes the affected components. Null struct padding is not evidence.
- Published metadata is selected only after successful preparation and
  validation (`catalog_publication.py:91-118`). The immutable stream does not
  replace the selected generation on its own.

## 4. Tests and concrete edge cases

| Test | Location | Trace and result |
| --- | --- | --- |
| New rows preserve saved filename metadata; explicit rebuild replaces it | `tests/test_incremental_catalog.py:17` | Old key comes from prior cache, new key is parsed; explicit force reparses both; passes |
| Unchanged update performs no receipt/body I/O or publication | `tests/test_incremental_catalog.py:35` | Matching prefix/seed and completed selected pair return early; passes |
| Filename and negative body results survive code changes | `tests/test_incremental_catalog.py:101` | Altered fingerprints preserve cached results; explicit force repeats inspection; passes |
| Source parser changes require explicit repair | `tests/test_incremental_catalog.py:154` | Same captures remain unchanged; repair replays retained receipt; passes |
| Same filename with replacement bytes does not inherit old content | `tests/test_incremental_catalog.py:531` | Body cache keys differ, source dictionaries remain unmodified; passes |
| Transitive merge/split and unaffected groups | `tests/test_catalog_staging.py:38` | Membership/signature comparisons invalidate only affected components; passes |
| Group policy changes with nested occurrences | `tests/test_catalog_staging.py:95` | Null-normalized signatures permit saved group reuse; explicit force uses changed rules; red before correction, green afterward |
| Later alias contributes cached native XML facts | `tests/test_catalog_staging.py:360` | Shared facts finish before finalization; early typed row inherits late qualifying evidence across 4,096 rows; passes |
| Reads never implicitly update disk rows | `tests/test_catalog_staging.py:412` | SQL trace has no read-side updates and one update for one changed row; passes |
| Capture can resume before publication | `tests/test_raw_capture_only.py:47` | Receipts/retry state persist; selected pair stays unchanged; later explicit publication includes capture; passes |
| Update-only never starts acquisition | `tests/test_raw_capture_only.py:124` | Missing worker path is never opened; unchanged catalog and capture state survive; passes |
| Failed or competing publication preserves selected pair | `tests/test_catalog_publication.py:36`, `:54`; `tests/test_standalone_catalog_publication.py:44` | Failed upload/selection cannot replace manifest; passes |
| New metadata columns survive without a whitelist | `tests/test_document_filename_index.py:161` | Schema follows consumed stream and metadata types; passes |
| Workflow event/mode boundary | `.github/tests/test_raw_source_workflow.py:69` | Executed shell routing produces capture-only, update-only, or explicit rebuild arguments; passes |

The final offline suite passed **6,652 tests and 31 subtests**, with five native
fetch checks skipped because `SOURCE_FETCH_BINARY` was unset. No Rust code
changed. The sample comparison matches all complete source/document records and
field schemas. Ruff reports the same 19 findings as HEAD and no new findings.
The installed actionlint passes with its unsupported `queue` key diagnostic
excluded; that is a validator limitation, not an unqualified full lint pass.

## 5. Findings

1. **Resolved correctness finding:** caller-owned source dictionaries were
   initially modified during streaming. Copying each dictionary before
   enrichment restored replacement-body, removed-evidence and replay behavior.
   Evidence: `stream-pipeline-tests-1.log` versus `stream-pipeline-tests-2.log`;
   corrected location `document_index.py:2171`.
2. **Resolved correctness/performance finding:** previous Parquet rows included
   null struct fields and a derived document family, causing equivalent input
   evidence to miss group reuse. The signature now normalizes those differences.
   Evidence: `nested-reuse-red.log`, `reuse-green.log`;
   `catalog_staging.py:297-304`.
3. **Observation — qualification boundary:** the two output files are about
   13.6% larger on the sample because output batches are smaller. Runtime falls
   45.0%; maximum measured parent memory stays approximately 519 MiB. The full
   hosted corpus and multi-worker aggregate memory remain unqualified.
4. **Observation — remaining I/O:** SQLite grouping still reads indexed component
   rows, publication validates outputs, and optional body/legacy recovery has
   separate I/O. This patch removes repeated filename-enrichment rewrites; it
   does not establish a single physical read across the entire pipeline.

## 6. Conclusion

**VERDICT: APPROVE for the scoped local change.**

The patch achieves explicit metadata reuse and removes the repeated enrichment
rewrites while preserving tested source evidence and publication behavior.
Coverage of changed paths: **ADEQUATE**. Confidence: **MEDIUM**, because full CI
corpus runtime/memory has not been measured. No commit or push was performed.
