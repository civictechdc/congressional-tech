# Historical D comparison: one-pass context reads and the original cache gate

This isolated D comparison retained the implementation that builds flat filters and the identity-sorted
`source_occurrences` list together. It checks recorded `source_link_url` values
directly when preparing source rows, including unpaired legacy filters. Returned
lists belong to the reader, so row merges cannot alter retained context. The initial D commit added no cache or finalization lifecycle. The later user
instruction asks for an aggregate runtime, memory and complexity decision; see
[the direct integrated F comparison](../process-efficiency-f/report.md). The
original measurements and threshold decision below remain historical evidence.

On the constructed high-fanout fixture, one-pass association time improved 11.2%
and complete rebuild time improved 4.0%. All twelve timed runs matched every
source/document field, nested value and list order. The comparator deliberately
ignores top-level Parquet metadata and row order, retaining exact field metadata,
field types and duplicate-row multiplicity. This is a bounded local result, not
a full-catalog or live-publication qualification.

A supplemental check of all 24 retained output tables also passed exact physical
row order and every required top-level metadata value, without rerunning timings.
It allowed only `catalog_id`, `source_fingerprint`, and
`document_grouping_fingerprint` to differ. Catalog IDs match both tables and the
selected result; both implementation fingerprints were independently recomputed
from the archived source for each arm. No timestamp metadata fields were present.
`evidence/ordered-metadata-comparison.json` retains the complete metadata values,
ordered row hashes, original file hashes and per-run checks. Reproduce this check
with `verify_order_and_metadata.py` against the retained local outputs.

The cache missed its preregistered gate: association time improved only 12.3%
(20% required), and its maximum sampled process-tree resident memory increased
3.0%. Its complete rebuild median improved 9.8%, but it did not override the
two failed conditions under the original decision rule. The rejected code and its tests remain available in
`rejected-cache.patch`, which applies to this one-pass implementation.

| Comparison | Arm | Association median | Complete rebuild median | Maximum sampled RSS |
| --- | --- | ---: | ---: | ---: |
| Cache, 3 alternating pairs | Baseline | 1.7101 s | 16.7191 s | 355,794,944 bytes |
| Cache, 3 alternating pairs | Cached candidate | 1.5000 s | 15.0726 s | 366,395,392 bytes |
| One pass, 3 alternating pairs | Baseline | 2.0499 s | 19.0970 s | 364,699,648 bytes |
| One pass, 3 alternating pairs | Retained candidate | 1.8194 s | 18.3345 s | 365,293,568 bytes |

Each comparison has its own contemporaneous baseline. Timing ranges overlap:
one-pass association was 1.7099–2.5782 seconds against baseline 1.8592–2.2688;
complete rebuild was 17.9598–20.1303 against 18.9527–20.7292. One-pass maximum
sampled memory increased 593,920 bytes (0.163%); no memory reduction is claimed.
Three repeats measure variation on this fixture, not coverage of other catalogs.
All runs stayed below the 2 GiB ceiling.

The fixture contains 32 exact URLs, 64 publisher observations per URL and 16
original source rows per URL. Rebuild adds one URL-derived filename per URL,
giving 544 source rows and 544 document rows. Each row's context must retain
original parent/title/hash/label/receipt pairings. The final candidate reported
544 result reads, 576 occurrence scans and 34,848 occurrence decodes. These
counters cover context result reads and the link predicate; they do not count
decoding during transfer propagation or meeting refresh. A result lookup scans
each occurrence once, verified on both resident and SQLite-backed context.

The cached candidate reported 480 hits, 64 misses and 37 evictions, with a peak
charged cache size of 1,046,153 bytes under its 1 MiB budget. Evictions required
later rescans: it decoded 4,128 occurrences. The much smaller decode count did
not yield the required association improvement. Per-row merge/normalization and
the remaining rebuild stages still perform work; the measurements do not isolate
their exclusive CPU costs. Increasing the cache budget was not tested or adopted.

The comparison used Python 3.12, PyArrow 25.0.1 and the locked Linux image
`sha256:1203f1822ae63fa6c2dda0b56cbd0a3902564fbc46aed617e0abfc5d6c567d21`,
two Docker CPUs, one filename worker, a 2 GiB limit and network disabled. Code
and inputs were mounted read-only. `/proc` process-tree RSS was sampled every
250 ms during the complete rebuild, including its own table validation and local
publication. Independent canonical comparison and input rechecks are recorded in
`qualification_elapsed_seconds`; their median was 22.9459 seconds for the
one-pass comparison baseline and 22.0421 seconds for its candidate. Other host
applications remained running; environment/C benchmark work was held while D
timings ran. Operating-system cache state was warm and uncontrolled.

The first untimed fixture omitted the publisher basis needed by the legacy
restore path. It was corrected before timing. A baseline reference-generation
preflight then intentionally differed from its unexpanded input; its original
failed comparison remains under `output/process-efficiency-d/reference-preflight`.
No timing retry or failed timed run was omitted.

The final focused checks cover resident/SQLite equality, legacy filters, detached
large values, reverse-arriving links, redirect cycles, incremental context and
complete raw rebuilds. Commands and results are in `evidence/correctness.txt`.
Cache-specific mutation, eviction and oversize tests passed before rejection and
are preserved in the rejected patch rather than maintained as a second route.

`plan.md` retains the original decision criteria. `evidence/` contains summaries,
the original run commands, source/input hashes and compressed unmodified reports.
The compressed frozen inputs retain only this constructed fixture and its exact
reference pair. Full local snapshots, outputs and logs remain in the worktree's
ignored `output/process-efficiency-d/` directory. To reproduce, prepare the image
through the root developer environment, restore the frozen fixture/reference,
archive baseline revision `24137dd08241c34f1632afcd78a80a6138e5779d`, and use
`run_pairs.py`; it calls the maintained `scripts/benchmark_core_rebuild.py`.
