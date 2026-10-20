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

## First dependency implementation increment

`catalog_dependencies.affected_sources` now accepts exact keyed source and
reverse-alias lookups. It closes saved old aliases and current replacement aliases
before returning source inputs. A bridge deletion reaches both former sides;
a new bridge reaches existing neighbors. Unknown deleted sources, missing
referenced sources and incomplete self-membership refuse with `DependencyGap`.
No change performs no lookups. The maintained grouping implementations and this
lookup now share `source_identity` and `group_aliases` in `document_index.py`;
source/document ID and group eligibility rules remain the same.

`NativeCatalogDependencies` reads explicitly routed native pins. Typed dependency
rows retain nested source values, immutable source order and saved aliases from
the prior rules. Reverse rows retain each alias/source pairing. It validates
schemas and source identities; native schema metadata is not mistaken for the
application schema. An actual local native test retains duplicate nested source
observations and orders 37–39, then uses those exact stored rows to close the
bridge deletion. A targeted rule-upgrade test verifies that saved old aliases
remain available when the current grouping policy changes.

This increment supplies the domain lookup and scope computation. It does not yet
implement durable routing writes, resumable traversal within a large component,
source/document candidate publication or maintained caller migration. The scope
currently retains its affected source dictionaries and membership sets in memory;
its total memory depends on affected-component size. Those boundaries must be
implemented and measured before this ticket can claim bounded resumable updates.
Native tests use the shared finite local fixture limits, independently of
production configuration. The primary checkout retains test results under
`output/incremental-updates-20261019/catalog/closure-increment-final-tests.xml`.

## Persisted routing increment

`CatalogDependencyStorage` now prepares source leaves and alias member leaves
through the shared `RoutingPages` and maintained native `run_table` API. A routed
alias directory points to another bounded routing root for its members, so one
large alias cannot become an oversized list inside a single stored row. Each
native dataset name binds exact typed content; the application later selects the
complete source/alias root pair. This path has no mutable per-partition head.

The native fixture retains old and new roots, reads them with a fresh domain
owner, preserves imported source order, and repeats the deletion with identical
retained file hashes. No-change and identical-replacement tests perform no native
or metadata writes. Missing reverse-directory counts, undeclared source fields,
wrong schema/budget bases and oversized leaves refuse explicitly. Source schema
evolution and changing partition budgets are not implemented by this increment;
it never drops unknown fields or responds with a global rebuild.

The retained local proof is
`output/incremental-updates-20261019/catalog/routed-dependencies-1/summary.json`.
For the same bridge deletion with 10 and 1,000 unrelated sources, a cold routing
owner made 16 partition calls in both cases and consumed 26 versus 22 Arrow rows.
It submitted 5 versus 4 Arrow rows. Metadata reads grew from 13 / 6,616 bytes to
26 / 43,371 bytes as the routing depth increased. These growth measurements use
an Arrow transport recorder and measure application lookup scope, excluding
native execution and physical I/O costs. All source fields matched an exhaustive
offline reference after the measured path. A separate three-source case executes
the actual local native lifecycle and retains its workspace and metadata roots.
No throughput improvement or production custody result is inferred from it.

Reproduce with the configured native binary and a new output directory:

```sh
PYTHONPATH="$PWD/packages/congress_api/src" python docs/experiments/incremental-catalog-20261019/measure_routed.py --binary /absolute/path/docspec --output /new/routed/evidence
```

This still prepares dependency state only. Grouped source/document candidate
integration, complete retired-component ownership proof and resumable processing
inside a large component remain required before replacing maintained callers.
