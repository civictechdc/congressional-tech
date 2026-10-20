# Incremental catalog publication boundary

`ct-v5kb` remains incomplete. The bounded local DocSpec proof does not yet
provide qualified transport and custody for the existing R2 catalog publication
path. The current conditional selector and every runtime reader remain unchanged.
This note preserves a reproducible failing acceptance case and the affected
consumer inventory; it does not claim production adoption or incremental delivery.

## Candidate partition reader

`retention/catalog_partitions.py:CatalogTable` now reads exact selected
source-only native pins through the shared `NativeDatasets` adapter. It accepts
the original application Arrow schema, checks logical field types and
nullability before restoring that schema's metadata, and verifies each consumed
partition's row count. Requested partition/column scopes must name distinct
selected values; unknown scopes refuse before payload reads. It does not resolve
native latest heads, approve source/document references or select publication.

Twelve focused tests passed, including a real local native source build/read,
exact nested values/schema metadata, skipped unrelated partitions, scope
refusals, schema/nullability mismatch and row-count mismatch. Together with the
29 existing publication/pair/consumer checks, 41 tests passed in 2.14 seconds.
The receipt is `publication/reader-core-final.xml`. The two diagnostic acceptance
failures for value fidelity and old-snapshot preservation were also exercised by
focused fault injection; `publication/review-correction-verification.json`
records their rejection. An earlier injection targeted the wrong temporary path;
its failed assertion remains in the local evidence directory.

The candidate reader follows the selector's partition order. An explicit
`order_column` enables sorting one bounded native chunk by nonnull unique int64
positions, then removes that internal field from the logical result. Callers
must provide `max_ordered_bytes`; the reader refuses larger observed Arrow input
before sorting. Sorting also allocates output and index arrays, so this is not
a whole-process memory guarantee. Without an explicit order column, rows follow
the native stream. Catalog computation must retain application order and select
chunks in the correct order before deriving mappings. No maintained consumer has switched
to this candidate API, and no v2 publication selector has been introduced.

## Measured current behavior

The fixture contains two logical tables, each with unique source/document IDs,
nested provenance, ordered duplicate values, Unicode, null lists, empty lists,
null reviews and empty reviews. A correction changes one filename review.
The documents file remains byte-identical, and `catalog_id` remains fixed to
isolate delivery from the application's catalog computation.

`scripts/measure/measure_catalog_partition_reuse.py --require-reuse` exits 1:

- Publication uploads the unchanged documents file under a new immutable key.
- Reading the previous selection copies and hashes both old payloads.
- Publication hashes the unchanged documents input again.

| Rows per table | Old payload reads / bytes | New payload writes / bytes | Reused bytes | Selector reads / bytes | Selector writes / bytes |
| --- | --- | --- | --- | --- | --- |
| 8 | 2 / 11,608 | 2 / 11,655 | 0 | 2 / 1,000 | 1 / 500 |
| 80 | 2 / 96,250 | 2 / 96,298 | 0 | 2 / 1,008 | 1 / 504 |

These are measured `LocalStore` call counts/bytes, not operating-system I/O or
R2 provider measurements. They exclude validator reads, footer reads and hashing
inside copies. The diagnostic separately records calls to publication's
`file_identity`. Both cases preserve the exact nested schema and ordered values
in selected files and retain the original selected payload hashes. Fixtures are
synthetic; these numbers do not estimate production savings or speed.

The existing publication, pair-validation and maintained-consumer tests passed:
29 tests in 2.21 seconds. They cover coherent pair selection, interrupted uploads,
competing local writers, corrupt/missing selected files, reference validation and
selected-generation use by archive/probe readers. They do not qualify partition
selection, durable cross-process validation reuse, provider lost acknowledgments
or cross-host native custody.

Local evidence is retained at
`output/incremental-updates-20261019/publication/`: `baseline.xml`,
`red-8/summary.json`, `red-80/summary.json` and `remote-feature.json`, including
exact manifests, operation records, fixture/selected payloads and the binary
identity of the refused native command. Run with a new output path:

```sh
python scripts/measure/measure_catalog_partition_reuse.py \
  --output /new/local/publication-proof --rows 8 --require-reuse
```

## Native boundary that must be qualified first

Inspected DocSpec source is `91eb44f520221ec91897403e930d23f491b5ffd0`.
`TablePin` and `ReleasePin` name exact metadata and object inventories
(`src/model.rs:73`, `:169`). The foundation's retained pins contain absolute
producer-host filesystem paths, including paths inside Iceberg metadata and
manifests. A serialized pin grants no retention lease or host custody
(`src/engine/backfill.rs:222`).

The maintained local independent `read --group source` command bypasses the
producer catalog (`src/main.rs:431`) and opens exact files through filesystem
I/O (`src/storage/pinned.rs:14`). This can support same-host native reads; it
does not establish a fresh R2 consumer's access to those paths. The Rust
`open_pin_with_io` API accepts configured object I/O (`src/storage/pinned.rs:38`),
but this inspection does not establish a portable transfer/import lifecycle.

The public `ExportSpec` authorizes one complete primitive-column distribution
(`src/export.rs:16`, `:40`); it rejects nested output types
(`src/engine/export.rs:859`). It cannot preserve these nested tables or provide
reusable native partition delivery. Repacking both tables after every update
would leave the failing acceptance case intact.

The maintained remote source-only engine uses a configured Iceberg REST catalog
and S3 object storage (`src/storage/remote.rs:108`). The original foundation CLI
build had no `remote` feature; that binary's remote startup refused `remote_feature`
before opening a workspace (`src/main.rs:1096`). A direct local attempt returned
`Error: remote_feature: remote startup requires the remote feature`, exit 1,
without creating the requested workspace or Arrow output. This checks the
supplied binary's compiled capability; it does not test remote provider access.
The later remote-enabled build removes that compiled-capability blocker. The
actual existing-bucket native Build instead failed catalog-side HTTP 424/401
authentication; provider qualification remains incomplete. Catalog setup retains
that separate evidence under `output/incremental-updates-20261019/catalog-setup/`.
Congressional-tech's existing R2 object client is not an Iceberg REST catalog.
The parallel raw-custody work owns the new native custody proof.
No alternate importer, rewritten native metadata, copied lifecycle catalog,
new external service or second application persistence engine was introduced.

Application-computed catalog rows could be persisted as source-only native rows,
with explicit application grouping/review rule versions. That does not require
pretending `RunSpec.definition` is the application's rule-version mechanism.
It also does not resolve remote custody or coherent application selection.

## Maintained consumer inventory

The migration must change the shared table-reading boundary and its actual
callers together. Replacing only the writer would break these assumptions.

| Consumer | Current dependency | Required migration |
| --- | --- | --- |
| `catalog_publication.read_catalog`, `local_catalog_paths` | Two whole selected files; copy/hash both into an owned snapshot; `_manifest` requires generation-local pair paths | Select exact native partitions under the existing conditional `indexes/catalog.json`; admit changed partitions and retain unchanged proof/version bindings |
| `raw_catalog.rebuild_catalog`, `_publish_result` | Open both previous `ParquetFile` objects; upload previous whole tables to `catalog-history` before publication | Read affected partitions and retain unchanged versions without a full-table history copy |
| `document_index` source refresh, inventory, review and local-result entry points | Read `snapshot.filenames_path` and `snapshot.documents_path` as single Parquet files | Read selected partitions directly; an optional explicit export must not become routine preparation |
| `raw_archive.Archive` initialization | `read_catalog` when selected fingerprint changes; reads filenames to restore source state | Restore from selected native source partitions without reconstructing unrelated tables |
| `catalog_validation` | `CatalogReferenceValidation`, `CatalogContentValidation`, `CatalogPairValidation` use process IDs, inode identity and weak issued-object registries | Bind durable semantic validation to exact immutable partition versions, validator/runtime identity and qualified custody; stale requirements must refuse |
| `corpus_recovery.publication.publish_imported` and `scripts/corpus_recovery/dispatch_corpus_recovery_publication.py` | Validate the full pair plus imported-body coverage; prefix-preservation work shares the old whole-file representation; dispatch dynamically imports both viewer scripts | Use the same retained versions as normal updates; preserve complete imported-body and mapping checks |
| `apps/site/scripts/publish-filename-viewer.py` | `_manifest`; download/hash both selected files; open whole filenames/documents and repack them | Consume selected partitions during preparation without an implicit full native export |
| `viewer_publication.attempt.prepare` | **Dynamic import** of `publish-filename-viewer.py`, then download selected manifest files before `builder.publish` | Migrate this dynamic path along with direct imports; preserve guarded preparation/continuation |
| `docs/youtube-coverage/research/scripts/view_document_filenames.py:Catalog._initialize` | **Dynamically loaded** by viewer publisher; `local_catalog_paths`, single `ParquetFile` pair, full grouping columns | Use exact selected partitions while preserving identities/mappings; browser stable-identity work belongs to `ct-ihve` |
| `docs/youtube-coverage/research/scripts/probe_document_links.py:archive_reader` | Resolve local selected pair, read filenames columns | Query selected source partitions without a whole-file compatibility export |
| `congress_api.cli.document_index`, benchmark/replay tools | Root pair detection, `local_catalog_paths`, exact selected-file comparisons | Make explicit export/diagnostic operations distinguishable from update dependencies |

The store namespace guard in `derived_files.require_derived_key`, local
`put_catalog_manifest` compare-and-replace and R2 ETag conditional writes also
require coordinated changes. The existing selector remains the publication
authority. Native lifecycle completion is preparation evidence; it is not
application publication approval or delivery.

After native custody is qualified, red acceptance must additionally cover
changed/reused partition proofs after restart, stale validator requirements,
missing/mixed partitions, competing writers and lost selector acknowledgments.
No green result for those unimplemented behaviors is asserted here.
