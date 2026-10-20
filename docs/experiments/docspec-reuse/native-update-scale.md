# Native Update efficiency: measured scale decision

Keep the narrow native correction in `62e8401`: it removes one unused catalog
registration and metadata JSON without changing data writing, ownership,
selection or stale-base checks. Native Update already beats full Build for the
tested 100,000-row datasets; its advantage comes from sharing unchanged payload
files. The correction does not change that algorithm or establish a universal
speed improvement. Application Update adoption remains open in `ct-eipa`.

The old 16-row comparison in congressional commit `74cff4c9` is retained as
baseline evidence. It does not justify rejecting Update at larger scale. Native
optimization is `ct-xl0y`; lifecycle-history costs are tracked in `ct-wmtx`.

## What was checked

129 cases completed exact old/new value, schema and ordinal checks, plus hashes
of every original source object. That is 258 old/new source checks, not 258 unique
snapshots. One seed-only `oversized_batch` refusal is preserved separately.
The whole measurement interval was 963.39 seconds, retaining 3,350,363,091 fixture
bytes (3.12 GiB), within the original 1,800-second / 4 GiB allowance. Native byte,
free-space, temporary-file and RSS observations are sampled; work can grow
between samples. Followup launchers subtract all completed/incomplete fixture
directories and elapsed wall time from the same original allowance.

Inputs were generated locally through batches of at most 1,024 rows. The schema
uses the application's raw state fields and reserved order/key fields, plus a
nested struct containing maximum UInt64 and null, empty and duplicate binary
values. Each material case changes one complete row or deletes one key. No real
records, provider calls, runtime configuration, credentials or migration restart
were used. Other agent builds/tests were quiet during measurements.
Each arm starts in a fresh workspace with equal generated logical input; native
UUIDs and physical pins differ across arms. Each case preserves its own exact
initial source pin through history preparation and checks its old object hashes.

All timed arms use two compute threads, 512 MiB native memory allowance, 256 MiB
scratch, 1,024 batch rows, 4 MiB maximum decoded batch and 8 MiB metadata. These
are native resource allowances, not a claim that whole-process RSS stays below
512 MiB. Fast native calls can fall between RSS samples.

The native command interval includes CLI startup and hashing. Update also
includes small replacement/deletion preparation. Build's complete input
preparation is timed separately; at 100,000 rows its median was another
0.50–0.56 seconds. Application old-leaf reads are omitted. Independent streaming
readback is separate, including its CLI calls and returned Arrow IPC bytes.

## Repeated population result

Seconds below are medians of three matched, interleaved repetitions. Full ranges,
observer costs, counters and individual results are in
`native-update-scale-results.json`. Times include the same observer in each arm;
observer time has not been subtracted.

| Rows | Change | Build | Baseline Update | Candidate Update |
| ---: | --- | ---: | ---: | ---: |
| 10,000 | append | 0.590 | 0.708 | 0.647 |
| 10,000 | correction | 0.567 | 0.929 | 0.918 |
| 10,000 | delete | 0.627 | 1.108 | 0.907 |
| 100,000 | append | 2.309 | 0.787 | 0.783 |
| 100,000 | correction | 2.113 | 1.089 | 1.027 |
| 100,000 | delete | 2.095 | 0.960 | 0.947 |

For this schema, delta size and layout, the observed crossover lies between
10,000 and 100,000 rows. This does not locate an exact threshold. Wider payloads,
larger changes, different files or retained history can move it. There was no
reason to add a wide-payload or million-row arm after the repeated crossover.

At 100,000 rows, candidate Update median native writes were 8,356 bytes for
append, 1,475,851 for correction and 1,468,611 for deletion. Build wrote about
11.9 MB each time. Correction/deletion reused 10,469,052 source bytes. Median new
retained bytes were 0.392 / 1.875 / 1.847 MB for candidate Update versus about
24.1 MB for Build; those totals include native retained admissions and metadata,
but exclude the separately prepared Build input already present before the
operation interval. Native write counters and complete fixture footprints are
different measurements.

The application's default leaf limit is 8,192 rows / 16 MiB decoded. Its one-pass
history-zero correction screen was Build 0.538 s, baseline Update 0.861 s and
candidate 0.834 s. Larger-table wins do not qualify a larger application leaf or
settle the application's preparation/selection composition.

## Constant removed work, unchanged algorithm

Material Updates consistently registered five native tables before and four
after, and retained one fewer file. A corrected two-row smoke isolates an
891-byte unused key metadata JSON. Its removal does not imply the aggregate
retained-byte difference equals 891: other generated/encoded metadata varies.
The measured candidate's runtime changes overlap ordinary variation, including
an amended-layout correction outlier of 2.489 s versus baseline 0.996 s and
Build 2.301 s. That one-pass outlier remains in the evidence. Do not describe this
patch as a blanket speedup.

The production patch still materializes DISTINCT keys once through the original
bounded Parquet writer. It uses the source FileIO and exact protected attempt
path, with native field IDs and the original metadata bounds. Only the unused
catalog table/metadata write disappears; no in-memory key cache or second state
authority is added.

Let R be source rows, F source files, C affected files and K distinct affected
keys. Material Update still probes key columns for every file, then scans each
affected file for full replacement. Its prepared key view is executed again by
each probe/rewrite. Work is approximately O(R key values + (F+C)K + affected-file
payload), plus lifecycle work. Sharing payload avoids full rewrites; it does not
avoid all-file key discovery.
This expression describes source discovery/rewrite work; delta ingestion and
DISTINCT preparation are additional costs.

For 100,000 rows, the ordinary seed had four source files and reported four
append probes / five correction or deletion probes plus rewrites. The smaller
row-group seed had sixteen files and reported sixteen / seventeen. Native
`files_scanned` is assigned from file-plan counts, not physical I/O measurements.
In particular, an empty key scope uses `EmptyTable`, and the optimizer may avoid
payload reads despite that reported count.

A separate qualification-only DataFusion probe isolates the prepared-key side:
1 / 10 / 100 independently executed joins report 47 / 470 / 4,700
`bytes_scanned`. This proves repeated key-payload query work in the tested
pattern, not total filesystem/network reads. Physical backend request totals,
decoded key-row totals and complete backend bytes are unavailable here.

## Layout, history and no-op limits

The proposed 256 KiB seed refused a 311,112-byte decoded batch before comparison.
That is correct capacity enforcement, not an engine regression. The preregistered
replacement changed only the seed tuple to 1 MiB, with timed limits unchanged.
Both 4 MiB and 1 MiB seeds produced sixteen files: the writer's metadata/row-group
guard closes files independently. These two seed targets therefore do not isolate
file-count growth. The four-versus-sixteen comparison also changes row-group
geometry; it is a layout observation, not a file-count-only causal estimate.

History held the exact initial source TablePin and 8,192 rows unchanged through
0 / 8 / 32 empty native Updates. One-pass correction results:

| Prior empty Updates | Build | Baseline Update | Candidate Update |
| ---: | ---: | ---: | ---: |
| 0 | 0.538 | 0.861 | 0.834 |
| 8 | 0.595 | 1.951 | 1.841 |
| 32 | 1.026 | 4.525 | 4.326 |

At history 32, observer work inside the operation interval was 0.116 / 0.432 /
0.404 seconds respectively. It explains part of the growth, not all of it; these
are un-repeated screens and not a fitted complexity estimate. Preparing 32 empty
Updates cost 45.89–65.72 seconds. Native lifecycle reads/commits and accumulated
catalog state need profiling under `ct-wmtx`; do not delete recovery history or
weaken selection to hide this cost.

The experiment's guarded Build no-op performs zero native calls and zero writes
in its operation interval. It omits the application's prior comparison/read.
Empty native Update acknowledges/selects a new operation while keeping source
files unchanged; it retained roughly 345–349 KB and registered six tables before
or five after. These are deliberately different semantics, not equal no-op arms.

## Correctness, review and professor assessment

The structural test failed on baseline's `keys/metadata` directory, then passed
with seven focused writer tests. Thirty update/evidence-update tests passed.
The native repository gate passed formatting, all-target/all-feature Clippy,
346 library, 313 integration, 15 restore and two worker tests. The later ignored
scan probe passed separately, followed by final formatting/Clippy. Twenty-two
local harness checks cover bounded input, typed restoration, corruption,
duplicate/missing/out-of-range ordinals, bounds and history-pin preservation.
Parent independently reviewed native `62e8401`, driver `15d81900` and receipt
followups before screening.

Interruption before processing completion retains the original unretired
protection record and byte-identical key files. Retry succeeds after original
producer deletion. This proves retained ownership and admitted-input recovery;
it does not claim failed-attempt key files are reused. Existing native tests
continue to cover duplicate/null/composite keys, renamed/reordered fields,
schema IDs, old snapshots, changes and stale-base refusals.

Grades apply to this measured path, not the whole repository:

| Dimension | Before | After | Evidence / next remedy |
| --- | --- | --- | --- |
| Persistent ownership/work | C | B | Remove one unused registration/file; retain necessary result/change metadata. |
| Payload reuse at scale | B+ | B+ | Both Update versions avoid most writes at 100k rows; this benefit predates the patch. |
| Key-discovery growth | C | C | All-file probing and repeated key-view execution remain; qualify conservative file-bounds pruning. |
| Lifecycle cost | C− | C− | Same source pin grows materially slower with history; profile maintained phase/catalog paths. |
| Local recovery preservation | A− | A− | Failure ownership, admitted-input retry and old-pin checks pass; remote qualification remains separate. |
| Universal speed claim | Incomplete | Incomplete | Workload-specific timings, three crossover repetitions and retained outlier support no universal claim. |

Future pruning must reject only provably impossible files and otherwise scan.
Iceberg 0.10.1's metrics evaluator is private; public filtered planning may help,
but occurrence readers must use original whole-file descriptors. Missing,
truncated, null/default/type-ambiguous bounds require fallback. Large IN lists
also stop pruning conservatively beyond the dependency's 200-value threshold.

Application/native selection remains unresolved: an unselected native Update can
advance native latest and make the still-selected application base stale. The
real-native regression in `74cff4c9` proves that failure; independent Build stays
safe. This performance patch does not loosen `stale_base`. A native prepare-only
composition needs a separate ownership/concurrency design. R2 schema/backfill,
joined summaries, occurrence evidence and dependency comparison/refresh belong
to native feature/qualification lanes; this local experiment does not implement
or qualify them. Those lanes need engine-owned remote pinned inputs/schema
alignment, joins retaining original occurrence locators, and durable comparison/
refresh phases. A local fixture or an application-side copy cannot supply that
remote qualification.

## Frozen provenance and retained evidence

Baseline source is `91eb44f`; candidate production change is `62e8401`. CLI paths:

- Baseline: `/Users/mikewolfd/Work/docspec-worktrees/update-efficiency/output/update-efficiency-20261020/bin/docspec-baseline-817831`, SHA-256 `817831a55c4273d79b8a9653a0a0248caa3648242b7f5cbb6200164c62864dbb`.
- Candidate: `/Users/mikewolfd/Work/docspec-worktrees/update-efficiency/output/update-efficiency-20261020/bin/docspec`, SHA-256 `20a9fd8202c009696c9b2b9455bf54b5634cb9b6e9843f042081b72740993529`.
- Main driver `15d81900`: SHA-256 `ee7269158cde3966d803ee0f3848b2de742f7b7106a503d5215d8ff791ed5c28`.
- Evidence-only 1 MiB layout control: SHA-256 `9736f4650e368f14dfcde56459c396aa4028fb85e5a311e8de9e3c195f343840`; only the seed tuple differs.

An external build changed the primary native executable before the first smoke.
Pre-screen verification caught it. An exact baseline copy was recovered from the
isolated target cache and frozen before qualifying work; the changed primary and
its dirty source files were left untouched. `scale-smoke` is protocol-only with
the changed executable; `scale-smoke-pinned` uses the correct baseline. No
qualifying scale arm uses the changed executable.

Initial screening resolved the editable primary Python package. The recorded
logical/physical schemas and all eight invoked adapter AST bodies exactly match
the intended checkout; unused configuration tracking/raw lifecycle code differs.
Those cases remain accepted with corrected provenance. Subsequent runs explicitly
set PYTHONPATH to the intended checkout. Path/hash/mtime comparisons are retained.

All fixtures, stopped receipt, individual timings, command/byte counters, source
hash checks, import checks, allowances, freeze records and gate logs remain under
`/Users/mikewolfd/Work/congressional-tech/output/docspec-reuse-20261020/updates/`.
No fixtures were removed to make the budget pass. This is local tested evidence,
not a push, deployment, provider qualification or application adoption.
