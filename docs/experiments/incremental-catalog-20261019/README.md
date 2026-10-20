# Catalog dependency boundary counterexample

`ct-si9g` cannot qualify bounded catalog updates on the current maintained storage
boundary. This diagnostic preserves the current grouping policy and demonstrates
one specific failure: removing a source that bridges endpoint A to body B still
reads, traverses, validates and serializes unrelated catalog rows. It adds no
runtime implementation and makes no production adoption or speedup claim.

The baseline at `e076d11` passed 61 focused catalog tests before edits. The two
additional diagnostic tests pass with those 61 tests. The acceptance probe below
intentionally exits 2: tests of the diagnostic pass, while incremental acceptance
remains unmet.

## Exact change and preserved behavior

The constructed inputs contain `a.pdf/body-A`, `b.pdf/body-B`, and
`a.pdf/body-B`. Endpoint equality connects the first and third; successful body
equality connects the second and third. Deleting the third source removes the
bridge and splits the old three-source group into two one-source groups.
Unrelated sources have distinct endpoints and bodies.

The diagnostic calls the maintained `write_document_indexes` implementation,
then compares every output field and row multiplicity to
`prepare_document_indexes`, the existing bounded reference. It retains the
maintained source and document ID algorithms. Nested duplicate source
observations, null/empty lists, and the existing document-level evidence merging
rules participate in the comparison. This is grouping/validation evidence on
constructed already-interpreted rows, excluding receipt parsing, body inspection,
source acquisition, raw restoration, native dataset operations and physical I/O.

## Measured fixed-change growth

Evidence retained under
`output/incremental-updates-20261019/catalog/dependency-growth-final/` on the primary
checkout:

| Metric | 10 unrelated sources | 1,000 unrelated sources |
| --- | ---: | ---: |
| Old affected component members | 3 | 3 |
| Remaining affected component members | 2 | 2 |
| Recomputed groups | 2 | 2 |
| Prior source payload rows read | 13 | 1,003 |
| Prior document payload rows read | 11 | 1,001 |
| Current source rows visited | 12 | 1,002 |
| Reference-validation rows read | 24 | 2,004 |
| Serialized source/document output bytes | 60,676 | 218,129 |

The first two read counters wrap actual prior-file batch iteration. The current
counter wraps the supplied source iterator. Validation wraps actual Parquet batch
reads inside the maintained validator. Output bytes sum the two resulting files;
they exclude temporary SQLite, metadata and other filesystem activity. Receipts,
bodies and filename classification are outside this already-interpreted grouping
path and are not invoked. No elapsed-time improvement is claimed.

## Missing supported boundary

The current caller restores all prior source rows in `raw_catalog.py` and
`catalog_staging.py`, reconstructs grouping indexes, and validates the complete
pair. It stores no maintained reverse dependency lookup or independently selected
old group membership. A changed source key alone therefore cannot establish the
complete affected old/new scope without scanning old published payloads.

The qualified local DocSpec API can retain bounded source-only dataset versions,
but probes every file within a selected dataset. Deterministic partition names
could bound that work only after the application retains the reverse lookup and
exact version routing. They do not provide fresh-host lifecycle custody by
themselves. The raw workstream is separately checking the maintained remote API
and existing host-recovery configuration; this diagnostic does not replace that
owner with a new file store or SQL database.

The next implementation needs both a recoverable native partition lifecycle and
retained old/new dependency lookup. It must seed these from existing snapshots,
retain exact versions across interruption, and migrate raw/catalog/publication
callers together before deleting their full-pair restore path. Existing callers
remain in place because no replacement has qualified. Large-component resumable
processing, corrections/evidence edits, targeted upgrades and actual consumer
migration remain unimplemented; this report does not mark `ct-si9g` complete.

## Reproduce

Use the existing congressional-tech environment from this checkout:

```sh
PYTHONPATH="$PWD/packages/congress_api/src" python -m pytest -q tests/test_catalog_dependency_boundary.py tests/test_catalog_staging.py tests/test_incremental_catalog.py tests/test_raw_catalog.py
PYTHONPATH="$PWD/packages/congress_api/src" python docs/experiments/incremental-catalog-20261019/measure.py --require-bounded --output /new/evidence/directory
```

The output directory must be new. `--require-bounded` returns 2 when the fixed
change scans unrelated rows; `summary.json` names the failed acceptance boundary.
A successful diagnostic run does not imply successful incremental acceptance.
