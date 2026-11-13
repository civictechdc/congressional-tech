# DataFusion 55 qualification for ct-7t5p

The DataFusion 55.2 upgrade preserves published archive types and values. It pins the scheduler timestamp, URL state strings, filename lists, and capture receipt locator schema explicitly. Public fixture exports remained byte-identical on the historical DataFusion 53.1 runtime. The DataFusion 55.2 fixture produced the same 30 exports.

## Runtime and capture data

The final platform pins use DocSpec `98a2d54077390a70703af0277a9ac2df9ce14cef` and require `remote`. The Linux runner built and stripped its binary on native amd64 using Debian glibc 2.36. The Darwin build also includes Substrait. [Engine commit](https://github.com/Formspec-Labs/docspec-rs/commit/98a2d54077390a70703af0277a9ac2df9ce14cef) · [Linux build and test run](https://github.com/Formspec-Labs/docspec-rs/actions/runs/43367715137)

| Platform | Actual features | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Darwin arm64 | `remote,substrait` | 198,964,776 | `4c4a94c8638f7fcb7a0ca086e310cbe383df69518c24ab70143d1f6aa9512f28` |
| Linux amd64 | `remote` | 223,839,536 | `ae75bb55e932d9ed156766499ef756e59a23498324cb59f54a7187b892657da9` |

The locator schema change advanced the capture mapping version to `0402c626941453040e447eecd1d37a8bf10cee93160e4000b1d0d4d5d97987b0`. Rebuilding 35,897 original receipts produced 4,181,852 capture rows. Comparing the old and rebuilt generations found only the mapping version change. Native readback from `captures_df55_20261113` snapshot `4841796116729777945` matched the rebuilt schema and every row, with zero unmatched rows or invalid keys.

## Model and tests

Two production-scale trials found inflated memory reservations for ordered nested aggregates. The first refused a reported 2.4 TB reservation while collecting document references. A temporary SQL rewrite cleared that step and the next trial refused 7.4 GB while resolving meetings. The final runtime uses DataFusion’s supported grouped aggregate stream with the original model SQL and existing memory limits. Requalify the default stream when upgrading to a DataFusion version with columnar ordered aggregate state. [Upstream accumulator change](https://github.com/apache/datafusion/pull/24392)

The final Darwin executable reran the original SQL for both failed steps on frozen model inputs. Each produced 18,183 rows, byte-identical to an independently run DataFusion 53.1 predecessor. The retained-reference output covers 169,498 references. The independent check detected a planted ordering error in each result. Peak physical memory was 0.83 GiB for retained items and 0.88 GiB for resolved meetings. The complete private model on Congressional Tech `6cf029720c2ace4f33c21ef272217f22e2591066` completed all 329 steps in 393.7 seconds at 11.34 GiB peak physical memory. All nine invariant and completeness reports returned zero violations.

The DocSpec repository gate passed 1,104 Rust tests and 31 Dagster tests, with 19 expected ignores. It also passed formatting, Clippy, and the debug build. The new ordered-aggregate regression checks 4,096 groups and 16,384 ordered structs, including a null text field. The previous DataFusion 55 runtime requested 16.7 GB from a 512 MiB pool in the corresponding standalone reproduction.

All six native Linux offline shards passed on the final executable, with 13,433 tests and 31 subtests passed, three expected skips, and 47 deselections. Shards 1–4 and 6 ran at Congressional Tech `6cf02972`. Shard 5 first found a maintenance test that hard-coded the old capture table. Its full rerun at `4cba90b8` used the original executable and checked the configured target. All six file assignments match across the two test revisions and the integrated release source. [Original Linux run](https://github.com/Formspec-Labs/docspec-rs/actions/runs/43367715137) · [Shard 5 rerun](https://github.com/Formspec-Labs/docspec-rs/actions/runs/43373534939)

The guarded publisher promoted archive `55c14dcda87ae954583bf518050b3bd45db6aed49c88c53413260c1d092ef105`. The sealed candidate and public predecessor match on all published keys and values across five files with Parquet field ID changes. The capture profile’s only changed field is the DocSpec revision. The release note records the accompanying PDF merges. [Archive release](../releases/2026-11-13-55c14dcda87a.md)

The first DataFusion 55 runtime also passed all six offline shards on Darwin, with 13,435 tests, 31 subtests, one skip, and 47 deselections. The final Darwin runtime evidence covers both changed aggregate behaviors, the DocSpec repository gate, and the full frozen model.

## Evidence

The archive checkout retains native evidence under `.cache/archive-release/implementation/ct-release-20261112T2215/`.

| Artifact | Evidence |
| --- | --- |
| `df55-engine-fix/SUMMARY.md` and `df55-engine-fix/repository-gate.log` | Failure reproduction, repaired engine, and complete repository gate |
| `df55-engine-fix/qualification-summary.json` and `df55-engine-fix/jobs/` | Exact Linux source, binary digest, and offline shard outcomes |
| `ct-m3h3/step78-df55-production-verification.json` and `ct-m3h3/step80-df55-production-verification.json` | Independent full-row comparisons with planted ordering changes |
| `captures/compare-v2/generation-comparison.json` and `captures/remote-import-recovery-v2/verification-recovery.json` | Capture generation comparison and native remote readback |
| `release/darwin-engine-qualification/archive-model/result.json` and `release/darwin-engine-qualification/measurement/publish-watchdog.json` | Private whole-data model and resource observations |
| `df55-engine-fix/sealed-engine-causes-review.json` | Independent sealed-release review of the engine metadata changes |
