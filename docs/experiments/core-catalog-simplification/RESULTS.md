# Ordered metadata update results

The local filename-enrichment change passed the sample gate: complete records and
field schemas match, median elapsed time fell 45.0%, and maximum observed process
memory stayed at approximately 519 MiB. This is a bounded result, not a full CI
corpus or aggregate worker-memory qualification.

## What changed

Routine updates preserve saved source, filename, body, and unchanged group
interpretations across code changes. An explicit rebuild reapplies current rules;
rebuilding body interpretations also requires explicit body inspection. New
source evidence still updates affected groups.

The filename stage restores prior filename and body results together. It consumes
source rows in batches, extracts missing filename results, gathers shared body
and URL facts, and writes each temporary Parquet batch once. Once later aliases
are known, it reads those batches once into grouping. It no longer repeatedly
rewrites an entire intermediate row store for enrichment and column discovery.
SQLite remains for indexed facts and alias grouping. This does not make the
entire recovery/publication pipeline a single physical read of each file.

## Controlled comparison

Input: a deterministic sample of complete document groups from the retained
671,035-row snapshot: 10,489 source rows and 8,660 document groups.
SHA-256: `68b634c4f40f13a18cdfdb29b55f412f963fb4d0c328eaf07f598ff1622409c8`.
Each measured run used a fresh offline Python process, one filename worker,
explicit reinterpretation, and no body inspection. Timings include profiling in
both arms. No tests ran concurrently with the qualifying timings.

| Arm | Elapsed seconds, two runs | Peak process memory, MiB |
| --- | --- | --- |
| Frozen baseline | 32.343; 30.544 | 518.9; 479.7 |
| Ordered stream | 17.349; 17.246 | 518.4; 518.9 |

The comparison hashes every complete row with duplicate multiplicity preserved,
and compares field schemas exactly. Both source and grouped-document tables
match. Top-level generation IDs and processing-version metadata are intentionally
excluded because each publication creates a new generation.

Output row groups are smaller to bound buffered records. The two output files
total 9,472,841 bytes versus 8,339,883 baseline bytes, about 13.6% larger. The
runtime result applies to the complete intervention, not Parquet alone.

## Earlier attempts retained

The first SQLite candidate ran alongside tests and is excluded from timing
qualification. A later SQLite candidate took 31.290 seconds: no useful speedup.
Replacing its repeated rewrites with repeated Parquet rewrites improved runtime
but raised peak memory. These attempts are retained as diagnostics; they did not
pass the adoption gate. Ordering discovery before final enrichment removed the
rewrites instead of tuning their cost.

Artifacts are under `.cache/catalog-simplify-20261005/`: the frozen baseline,
intermediate source copies, `bench.py`, `sample.parquet`, per-run logs,
`profile.pstats`, `result.json`, and the full comparison in
`ordered-stream-2-comparison/result.json`. Regression failures and subsequent
passes are retained separately. The final nested-null signature correction
only affects reuse comparisons; it does not run in the timed forced-rebuild arm.

## Limits

The full hosted corpus has not been benchmarked with this patch. This does not
establish an 8 GiB full-rebuild bound or promise a specific CI runtime. Optional
body inspection, historical receipt recovery, indexed grouping, and publication
have their own I/O; this change does not assert one read across all those stages.
Unchanged-update regressions separately enforce no receipt/body reads and no
publication, including after code changes.

Final validation: 6,652 tests and 31 subtests passed; five native-fetch checks
were skipped without SOURCE_FETCH_BINARY. The 101 unrelated experimental files
match their saved hashes. No commit, push, or hosted run was performed.
