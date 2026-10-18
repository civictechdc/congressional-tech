# Keep file-backed catalogs and one-pass context lookup

F now reads, validates, archives and uploads catalog tables through owned files.
The existing 1.083 GB selected pair used 53.15% less maximum sampled resident
memory during isolated reading and validation: 1,875,550,208 to 878,702,592 bytes.
That saving cost temporary disk space and slower reads. The complete small
fixture rebuild showed overlapping runtime ranges and a higher sampled memory
peak; it does not establish a whole-pipeline memory or speed improvement.

The optional context cache remains unadopted. A direct comparison on the same F
baseline found a 3.27% median complete-rebuild gain, but the paired gains varied
from 1.64% to 7.10%. The benefit is too small and variable here to justify cache
finalization, eviction handling and additional oversized-record safeguards. This
is an aggregate runtime, memory, complexity and uncertainty decision under the
user's revised instruction, not the historical D 20%/zero-memory-growth gate.

## What changed and how failures behave

`CatalogSnapshot` owns verified `filenames_path` and `documents_path`, the captured
selector version, manifest and file identities. All consumers keep this snapshot
open through their last read and previous-table archival. Successful contexts
remove temporary files; failed contexts preserve their directory and include its
path in the exception. There is one production file-backed snapshot route.

`read_derived_file` and `put_derived_file` accept only the two exact root tables,
32-hex catalog generation paths and 64-hex history paths. Existing R2 body-file
methods retain their body-only restriction. Transfers use bounded chunks, size
and SHA256 checks, and version-pinned remote retries. Local immutable publication
uses exclusive hard links, so a concurrent destination cannot be overwritten.
The partial evidence link remains until directory fsync succeeds. Generation
files precede the small selector write, which still uses the version captured
before the build. Selected corruption fails without falling back to root files.

The same route now serves the raw rebuild, standalone metadata refresh/reindex,
archive bootstrap, benchmark overlay and recovery dispatcher. The dispatcher
saves verified derived files for its pair validator; its continuation client
already supports seekable file bodies. Local selected-table validation hashes
each file once, reusing that identity for metadata checks. Previous-table history
uses the already verified input digest and preserves byte identity.

Focused checks cover short/excess reads, checksum and version changes, failed
uploads, selector races, immutable-file races, directory fsync failure with an
existing diagnostic path, corruption without fallback, successful cleanup,
failed-snapshot retention, previous-file lifetime through archival, and unchanged
body-only guards. Final focused batches passed 111, 134, 79 and 57 tests (these
batches overlap); the experimental cache's focused batch passed 71 tests.

## Complete fixture comparisons

Each comparison used three fresh alternating pairs on the same constructed D
fixture: 32 exact URLs, 64 paired publisher occurrences per URL and 16 source rows
per URL. The complete rebuild produced 544 source rows and 544 document rows.
The two comparisons have separate contemporaneous controls; their differences
are not subtracted from one another or from the historical D runs.

| Comparison | Arm | Rebuild median | Qualification median | Maximum sampled RSS | Maximum sampled scratch |
| --- | --- | ---: | ---: | ---: | ---: |
| Catalog I/O | Previous bytes | 14.3705 s | 16.8370 s | 370,356,224 B | 64,522,079 B |
| Catalog I/O | Owned files | 14.1334 s | 16.4435 s | 384,327,680 B | 65,028,211 B |
| Direct F cache | One pass | 14.1284 s | 16.3877 s | 381,349,888 B | 65,289,098 B |
| Direct F cache | 1 MiB retained cache | 13.6663 s | 16.0312 s | 382,304,256 B | 65,289,098 B |

Qualification includes post-rebuild semantic comparison and input checks. The I/O
comparison's rebuild ranges were 13.4953–14.8383 seconds for bytes and
14.1258–14.5504 seconds for files. The median changed -1.65%, while maximum RSS
increased 13,971,456 bytes (+3.77%). No fixture speed or memory saving is claimed.
Peak scratch increased 506,132 logical bytes; allocated-byte samples are retained
separately because filesystem allocation varies.

In the direct cache comparison, the one-pass range was 13.9147–14.2887 seconds
and the cache range was 13.2737–13.8969 seconds. The ranges are only 0.0178 seconds
apart, while the cache's within-arm spread is 0.6231 seconds. Paired improvements
were 7.10%, 1.79% and 1.64%; qualification median improved 2.18%. Maximum sampled
RSS increased 954,368 bytes (+0.25%). All values and pair calculations are in
[`evidence/summary.json`](evidence/summary.json).

The experimental cache reported 480 hits, 64 misses, 37 evictions and 4,128 decoded
occurrences, versus 34,848 decodes for one pass. Its maximum retained charge was
1,046,153 bytes. This charge does **not** bound transient memory: `pickle.dumps`
serializes a complete result before rejecting an oversized entry, and Pickler
bookkeeping also allocates memory. A future cache would need safe admission and
new direct measurements on large records. The observed modest fixture gain does
not justify adding that complexity now. The candidate and its tests remain in
[D's retained patch](../process-efficiency-d/rejected-cache.patch) and the frozen
local `output/process-efficiency-f/sources/cached` tree.

## Separate existing-pair read component

The source was the verified local mirror selected by generation
`cbcf65877e2843ae8b23915c3d05a18f`, catalog ID
`76758ea73fa94075bda46ce79e569fd3`. Its tables contain 1,683,404 source rows and
1,241,131 document rows, with 544,061,564 and 539,110,541 compressed bytes. Both
SHA256 values and the selector were checked before and after the trials.

| Read/validation only, two alternating pairs | Bytes | Owned files |
| --- | ---: | ---: |
| Median elapsed | 2.6524 s | 4.5805 s |
| Elapsed range | 2.5010–2.8039 s | 4.4286–4.7325 s |
| Maximum sampled RSS | 1,875,550,208 B | 878,702,592 B |
| Maximum scratch logical bytes | 0 B | 1,083,172,637 B |

The measured tradeoff is 996,847,616 fewer resident bytes (-53.15%), a 72.69%
slower component median, and about 1.083 GB of temporary disk. All four processes
stayed under the same 2 GiB limit. These trials read and validate the pair only;
they do not decode all rows, rebuild a catalog, prepare a viewer or upload data.
The 1.083 GB selected input pair is distinct from the 365,992,473 bytes of
published viewer filenames/groups downloaded per unchanged recovery poll in the
delivery audit. F does not explain or fix the separate viewer-builder
out-of-memory failure.

## Verification, reproducibility and limits

All twelve complete runs passed the existing semantic comparator. A separate
check passed all 24 retained tables' physical row order and required top-level
metadata, plus prior-history digests. It allowed only fresh `catalog_id` values
and source/grouping implementation fingerprints. Pair IDs match the manifest;
fingerprints were independently recomputed from each frozen implementation.
No timestamp metadata fields were present. The large component selected exactly
the same manifest in all four runs and left its inputs unchanged. See
[`ordered-metadata-history.json`](evidence/ordered-metadata-history.json).

All trials used the pinned Python 3.12.13/PyArrow 25.0.1 Linux image
`sha256:c9d2d30b8afc862ec42f7879480624fc798473a54807b2610df471a4491d730c`, two CPU
quota, a 2 GiB memory limit, one filename worker, disabled network and read-only
input/source mounts. Memory and scratch were sampled every 250 ms; shorter peaks
may be missed. Each trial had a distinct owned temporary directory. OS caches
were warm and uncontrolled. These small repeated comparisons measure variation
on selected cases, not general catalog performance or live R2 behavior.

[`plan.md`](plan.md) records the decisions before timing. `freeze.py`,
`run_pairs.py`, `run_component.py`, `verify.py`, `summarize.py` and
`retain_evidence.py` reproduce the workflow. The unchanged fixture and reference
remain under `output/process-efficiency-d`, with frozen input bytes committed in
D's evidence. Exact source hashes, raw reports, command/image receipts, logs and
failure receipts are retained here; full generated outputs and frozen source
copies remain under `output/process-efficiency-f`.

Failed setup attempts remain in the evidence: the first pytest base directory
had a missing parent; one interim benchmark test detected the harness being
edited during its own pinned run; the dispatcher test needed the maintained
`scripts` import path; and an initial cache test invocation used the one-pass
counter expectations before applying the retained cache tests. Corrected batches
passed. For the component, the initial supplied identity was a catalog ID rather
than a generation, caught before timing; the first offline-wrapper invocation
then refused its argument form before importing or reading inputs. The corrected
`-m` invocation used a new evidence directory at unchanged limits. There was no
capacity failure or capacity retry.

This is local implementation and measurement evidence. No production source was
acquired, selected, published or deployed. Full-workspace integration follows
this commit and remains a separate gate.
