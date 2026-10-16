# Current catalog staging versus DocSpec: small benchmark

**Result: no measured elapsed-time improvement at 8,197 output rows.** DocSpec used less CPU time and additional disk, with higher sampled memory. It was slower at 1,029 rows. All twelve measured runs produced the same selected values and types, including nested source provenance. These results support further investigation, not adoption or a full-rebuild speed claim.

Three fresh-workspace runs per arm at each size; medians below. Each sample includes five explicitly constructed edge-case rows.

| Output rows | Current SQLite elapsed | DocSpec elapsed | Current CPU | DocSpec CPU |
| ---: | ---: | ---: | ---: | ---: |
| 1,029 | 0.72 s | 1.20 s | 0.47 s | 0.60 s |
| 8,197 | 1.53 s | 1.53 s | 1.19 s | 0.78 s |

At 8,197 rows, elapsed ranges were **1.46–1.56 s** for SQLite and **1.51–1.53 s** for DocSpec. The small difference is below the monitor’s 0.2-second polling interval. DocSpec used about **35% less CPU**, **53% less additional logical disk**, and **43% more sampled peak memory**. At 1,029 rows its median elapsed time was about 68% higher.

| Resource, median at 8,197 rows | Current SQLite | DocSpec |
| --- | ---: | ---: |
| Sampled peak aggregate resident memory | 174.1 MiB | 249.7 MiB |
| Sampled peak additional logical files | 69.7 MiB | 32.9 MiB |
| Sampled peak additional allocated files | 69.8 MiB | 33.1 MiB |

The measured association operation itself took 0.463 s for SQLite and 0.425 s for DocSpec at the larger size. DocSpec admission of both inputs added 0.514 s; its managed read and Parquet output took 0.122 s. SQLite loading took 0.252 s and output/close took 0.283 s. These phases have different guarantees: DocSpec’s join also retains contributor evidence, validates its result and selects an immutable version.

## What was compared

The baseline imports the unchanged `WorkingCatalog`, `DiskMap` and `merge_values` from the active recovery’s pinned catalog runtime. It loads source and prepared per-URL metadata maps, looks up and updates each source row, then writes Parquet. SQLite uses its maintained 8 MiB page cache. This is a harness around the existing staging primitives and association loop shape; it does not invoke the full `rebuild_catalog` function or construct `DocumentSources` context. Keys in the source working map use the already unique source IDs.

DocSpec uses the existing release CLI: admit both typed Parquet inputs, run its native many-to-one left join, retain contributor evidence and immutable selection, read the exact combined result through its managed Arrow reader, and write the same Parquet columns with PyArrow. The last write is a benchmark adapter, not the currently primitive-only authorized DocSpec export API or the production paired publication. No Rust engine code changed.

Both arms receive the same frozen files: 1,024 or 8,192 actual source rows selected from fixed, evenly spaced row groups in the retained pre-recovery `before-filenames.parquet`, catalog `4ca7d4a58bf04efc9e016e0cbacc3ef8`. The selected fields are source ID, body key, filename, original URL, six list-valued context fields and nested `source_occurrences`. The larger fixture has 6,595 prepared URL metadata rows containing 31,784 nested occurrences; the smaller has 825 metadata rows and 9,792 occurrences. Metadata combination is fixture preparation shared by both arms and excluded from timing. This is a selected sample, not a random or representative corpus.

Five constructed source rows test two sources matching one URL, an empty filename and empty lists, an unmatched URL, and a null URL. Exact multiset comparison checks all selected values, duplicate multiplicity, nested provenance, null versus empty and Arrow types after every arm. It does not compare physical row order, encoding, or format-specific Parquet field-ID metadata. All twelve outputs passed. Neither source preparation nor the independent Python equality check is included in the arm timings; both costs are outside both arms.

## Conditions and limits

- One compute partition, 1,024-row batches, low process priority, a 512 MiB DocSpec engine budget and a 2 GiB sampled process-tree ceiling. Actual maximum sampled aggregate RSS was below 251 MiB. Batch/metadata admission settings are retained in `limits.json`.
- Three alternating paired runs at each size, fresh workspaces and warm operating-system caches. No cache flush, build, download, remote write, or active-recovery modification occurred.
- The current recovery continued on this machine. Timings are exploratory and cannot isolate background disk contention; there is no idle-host or cold-storage throughput claim.
- The 0.2-second monitor samples resident memory and logical/allocated files. Unsampled peaks, physical I/O, OS page-cache memory and whole-volume free-space changes are not measured resource outcomes.
- Additional files include working databases, native data/lifecycle/evidence, temporary files and outputs. DocSpec also retains the benchmark Arrow read. SQLite scratch was intentionally retained for inspection even though production discards it. These figures are not long-term lifecycle storage or steady-state viewer size.
- Native release binary and source-checkout revision are independently recorded. The binary was reused and hashed, not rebuilt; source-to-binary reproducibility was not established by this experiment.

This excludes receipt replay, document parsing, metadata discovery, transitive document grouping, interpretation repair, nested paired export, R2 transfer/readback, viewer publication, incremental updates and restart qualification. The sample’s working set is tiny compared with the running recovery’s multi-gigabyte SQLite database. Do not extrapolate these timings to the full rebuild.

## Retained pilot failures

Fixture preparation initially parsed `docspec hash` as a bare digest; the maintained CLI returns JSON. That harness error and its partial fixture are retained. The first DocSpec pilot refused a shared-memory reservation with 64 MiB batch and 16 MiB metadata ceilings. The second admitted the source rows but correctly refused a nested batch of 8,430,593 bytes against an 8 MiB limit. The final profile uses a 16 MiB batch ceiling and 8 MiB metadata ceiling within the same 512 MiB engine budget. No fields were dropped. Both arms passed the resulting pilot before performance repetitions began. All amendments and failed outputs are retained, not included in successful timing medians.

## Decision

The declared 20% elapsed-time improvement threshold did not pass. The bounded result is a CPU/disk-versus-memory tradeoff and output-parity evidence for this small join. Continue to let recovery finish. A later migration proof still needs the complete semantics and full rebuild/incremental measurements from the migration plan; this benchmark does not authorize implementation, cutover, or deployment.

## Evidence

- [Frozen protocol](/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog-benchmark-20261013T2053Z/PROTOCOL.md)
- [Raw metrics and summary](/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog-benchmark-20261013T2053Z/summary.json)
- [Runnable harness](/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog-benchmark-20261013T2053Z/bench.py)
- [Input and binary identities](/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog-benchmark-20261013T2053Z/frozen.json)
- [Measurement freeze](/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog-benchmark-20261013T2053Z/measurement-freeze.json)
- Per-run directories retain CLI requests, outputs, errors, selected manifests, native files, metrics, and exact comparison results.
