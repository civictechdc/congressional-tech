# Local incremental storage boundary proof

The maintained DocSpec local API can own **bounded dataset versions and completed
changes**. This proof uses one retained GovInfo package. Its exact-base update
preserves nested values, duplicate observations, original receipt bytes and old
versions, and a fresh process reuses the completed update without producer inputs
or retained workspace changes. This is a local capability result, not production
adoption or end-to-end incremental qualification.

Congressional-tech baseline: `585b9ad`. DocSpec source:
`91eb44f520221ec91897403e930d23f491b5ffd0`, package `0.1.0`, with its locked
DataFusion `53.1.0`, Iceberg `0.10.1` and Arrow/Parquet `58` dependencies. A clean
`cargo build --locked --bin docspec` completed in 1m56s. The proof records the
binary SHA-256 and the engine's runtime/lock identity. No DocSpec source changed.

## Inputs, changes and verification

The tracked fixture is the exact 13,298-byte acquisition receipt for
`CRPT-118srpt180`, SHA-256
`cdeedf3059a62b81f77fd66215c8a8c7e7dc69e9322994a9164bb6507a659c86`.
Its exact retained object locator is
`audits/local-retention/20261019/sha256/cdeedf3059a62b81f77fd66215c8a8c7e7dc69e9322994a9164bb6507a659c86/receipt.json`.
The local ZIP and all five member bodies were checked against the receipt, using
only existing local files. The maintained source archive remains their owner;
DocSpec source rows retain their identities and receipt bytes, not another copy
of every body. No source or document mappings changed.

`scripts/incremental_boundary_proof.py` makes seven typed rows: the ZIP, five
members and one **constructed duplicate observation**. Repeated HTTP headers,
receipt paths/digests, member provenance and base64-encoded original receipt bytes
remain nested. The acquisition receipt is a JSON object: its locator uses a null
line and the empty JSON Pointer identifying the root, not a JSONL line number.
Constructed null/empty reviews and alias lists test their distinct
meanings. Occurrence keys differ from body digests; duplicate observations survive.

The executable change example names changed record keys, a deletion, old/new
alias edges and explicit `retained-package-v1` / `alias-v1` transform names. It
corrects one row's review and alias, deletes another row, and preserves all other
rows. The alias edit is stored source data; this does not claim that DocSpec has
executed the application's group merge/split rules.

The proof compares every selected field and duplicate count, including nested
list ordering, before and after the update. It independently rereads the old pin.
The native applied-change certificate names the exact before/after metadata and
contains one added and two removed rows. A second independent dataset in the same
workspace retains identical object bytes across the update.

## Actual maintained API

All requests go directly to the maintained CLI, each in a fresh process:

1. `hash SOURCE.parquet` returns JSON with a BLAKE3 `digest` and byte count.
2. `run build.json` accepts `RunSpec`: dataset, stable operation, input path,
   expected digest, explicit definition and `SELECT * FROM input`.
3. `plan-update update.json` and `update update.json` accept `UpdateSpec`: exact
   selected base ID, stable operation, active definition, key fields, replacement
   Parquet path/digest and deletion-key Parquet path/digest. Complete-key
   replacement is the API; this proof supplies unique occurrence keys.
4. `read-combined RELEASE.json OUTPUT.arrow` reads native nested data from the
   exact returned `ReleasePin`. `inspect-changes VERSION.json` accepts dataset,
   version and exact manifest reference. `inspect DATASET` exposes retained phases
   and their named metrics.
5. Repeat the **same `update` request** for a completed retry. `resume` is a Build
   command, not the Update retry API. New operations with an old base refuse
   `stale_base`; changed requests under the same operation refuse
   `operation_conflict`.

The operation ID hashes the fixture's explicit semantic change and fits the
native ASCII/128-character identifier limits. Real downstream callers must bind
their stable operation to their own input identities, exact bases and transform
versions; this fixture hash is not a new production protocol.

## Results and cost limits

Forty existing incremental-catalog/GovInfo tests passed before edits. Three new
fixture tests passed after the missing proof implementation was added. Native
execution separately passed exhaustive value parity, exact old-pin reads,
certificate bindings, stale/conflicting request refusals and completed replay.
Before replay the source/replacement/deletion files are renamed unavailable.
The returned release and retained phase records remain identical; hashes of
every retained workspace file also remain identical. This proves completed
replay after process restart. It does not prove mid-phase worker-kill recovery.

For the same correction/deletion, the controlled diagnostic uses a 64 KiB build
profile to create small native files and a 4 MiB update profile for joined rows:

| Rows in the target dataset | Initial data files | Update file scans | Reused files / bytes | New data files / bytes |
| --- | --- | --- | --- | --- |
| 7 | 1 | 2 | 0 / 0 | 4 / 60,451 |
| 70 | 4 | 5 | 3 / 236,929 | 4 / 118,866 |

The extra rows are explicitly constructed unrelated copies, not newly acquired
sources. `files_scanned` counts one key probe per existing file plus one full
read per affected file (`src/engine/write.rs:587-673`). These counters do not
include all metadata, validation, lifecycle, hashing or operating-system I/O.
The full inspection records retain admission, processing and validation phases;
filesystem measurements separately retain new objects and bytes. No throughput
or speed improvement is claimed from this small diagnostic.

The current `Archive` restore/append baseline starts with six capture rows and
adds the same retained package as six further observations: 2 object reads /
13,949 bytes; 3 writes / 21,266 serialized bytes; zero old body reads. This excludes
initial package preparation, catalog processing and preservation validation
(`validation_calls=0`). Its operation differs from the native correction/deletion,
so the byte counts are **not a comparative speedup**. The baseline exposes the
existing full capture/state serialization that ct-365w must replace.

A 64 KiB all-phases attempt correctly refused `oversized_batch` while adding
stored occurrence identity. Its partial outputs remain retained. A first harness
attempt completed native behavior but failed while decoding `inspect` as a list;
the CLI returns an object. That harness error is retained too. The profile
amendment was written after the development diagnostic runs; these are bounded
capability observations, not a preregistered performance comparison.

## Ownership and required consumer changes

Use DocSpec's demonstrated local dataset/version/change lifecycle for bounded
source partitions. The every-file key scan is bounded by the chosen dataset;
putting an entire corpus in one dataset would retain global scan work. Stable
partition routing and durable lookup for arbitrary corrections are application
work, not a demonstrated native record-key index.

| Consumer | Existing owner to retain | Required child work |
| --- | --- | --- |
| `raw_archive` | Acquisition decisions, body/receipt retention | ct-365w: bounded capture/state writes, occurrence identity, exact version routing, retry/concurrency checks and migrated readers |
| `corpus_recovery` | Normalized preparation, guarded conditional writes and readback | ct-365w: share the normal raw representation; replace full-table prefix preservation with exact retained-version reuse |
| `raw_catalog` / `catalog_staging` | Source/document identity, interpretation and grouping policy | ct-si9g: durable old/new dependency lookup, complete affected components, stored group/summary results, bounded resumable batches |
| `catalog_publication` | Coherent two-table selection and stale-writer protection | ct-v5kb: select changed/reused immutable partitions, bind durable validation to exact versions, migrate every maintained reader |

Those are authorized downstream implementation tasks. This proof adds no
second dataset engine, scheduler, runtime adapter, mutable latest pointer or
production dual writer. Downstream code should use native requests and exact
pins; the proof script remains a test tool.

The native public `ExportSpec` writes a complete primitive-column file, so it
cannot stand in for reusable nested partition delivery. Existing native exact
file pins may support a thin transfer path, but portable readback and transport
must be demonstrated. Native remote Update currently qualifies only source-only
independent lineages without computed groups/receipts. Full nested source rows
here do not qualify that remote lifecycle or native EvidenceSpec associations.
General incremental SQL and globally invalidated-source upgrades also remain
unsupported; application dependency/group computation cannot assume otherwise.
These are native engine limits. Application transforms can compute a changed
partition and store the result as source-only rows, with explicit application
rule versions, without using a native computed group or changing the active
`RunSpec.definition`. Their completeness, lookup, remote readback and publication
are downstream implementation and qualification work. This proof does not impose
an additional child-start gate: ct-365w, ct-si9g and ct-v5kb own those changes.

## Reproduce locally

Run from the congressional-tech checkout, with its dependencies available:

```sh
python -m pytest -q tests/test_incremental_boundary_proof.py
python scripts/incremental_boundary_proof.py \
  --binary /absolute/path/docspec-rs/target/debug/docspec \
  --output /new/local/proof-directory \
  --build-batch-bytes 65536
```

The exact fixture paths refer to already retained local bodies. Missing or changed
files fail; the proof never downloads replacements. Add `--copies 10` for the
fixed-change growth diagnostic. Every output directory must be new so earlier
failures and receipts remain intact.

Detailed local evidence lives under
`output/incremental-updates-20261019/foundation/`: `PROTOCOL.md`, `raw-baseline.json`,
native requests, stdout/stderr, source/expected references, original pins, change
certificates, full retained phase records and `summary.json` per completed case.
`reviewed-1x` and `reviewed-10x` are the final cases with the corrected JSON-root
receipt locator; the earlier cases remain historical development evidence.
Sibling `capability-audit.md` and `consumer-inventory.md` record the inspected
native limits and maintained/dynamic reader inventory. No remote mutations,
production migration, operational rebuild, classifier change or new source ran.
