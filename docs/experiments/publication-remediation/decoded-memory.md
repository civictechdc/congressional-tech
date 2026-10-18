# Decoded viewer preparation memory

`ct-hnxb` adds byte admission before Python conversion and JSON processing, a
source-bound observation-count handoff, and a disk-backed observation identity
index. All ordered source values remain in the full Parquet exports. Repacking
still compares every Arrow value and schema metadata. Observation verification
still reconstructs and compares every observation and reference; detail
verification still checks every emitted field, including UTC timestamps.

The default policy is explicit in `filename_budget.DecodedPolicy`:

| Admission | Default | Meaning |
| --- | ---: | --- |
| Native decode rows | 128 | Maximum requested rows per native batch, within one physical row group |
| Physical uncompressed group bytes | 64 MiB | Footer preflight of selected encoded column chunks, before decoding any group |
| Ordinary admitted Arrow bytes | 4 MiB | Larger returned batches split before Python conversion |
| Ordinary Python/JSON estimate | 32 MiB | Payload factor plus explicit nested list/struct and field-name accounting |
| Single-row Arrow bytes | 16 MiB | Explicit oversized-row path; stricter Python estimate also applies |
| Single-row Python/JSON estimate | 128 MiB | Larger rows fail visibly; no truncation or dropped fields |
| Logical JSON value | 32 MiB | Serialization and logical block reconstruction limit, distinct from 1 MiB parts |
| SQLite cache per index | 8 MiB | Observation identity and verification dictionaries spill to temporary files |

The physical limit is conservative admission, not a decoded Arrow allocation
bound. Parquet dictionary and repetition encoding can expand before Arrow
returns even one row. The native row cap limits multi-row amplification; an
individual nested row can still expand substantially inside the native decoder.
Actual returned Arrow bytes and the estimated Python working set are checked
before `to_pylist`. Slices and zero-copy coalescing can retain larger underlying native buffers.
Summed `nbytes` measures logical admitted data, not retained allocation. Metrics
also record `get_total_buffer_size()` for native/admitted batches and coalesced
repack tables; Arrow deduplicates shared buffers within each measured object.
These per-object maxima do not measure all simultaneous process allocations. Global catalog
navigation indexes, codec buffers, parser allocations and runtime memory remain
additional costs. This policy and the fixture watchdog do **not** provide a
universal process resident-memory guarantee.

The 64 MiB physical default leaves room above the observed largest physical
filename groups in two retained local catalogs: 30,575,188 bytes across 1,633
groups / 1,672,092 rows (`ee9bbad71e4648ffbcacb63ccb8bebe2`) and 33,843,154 bytes
across 1,001 groups / 1,024,227 rows (`60321acca79849e6ba2487f618bef139`). These
were footer-only observations, not complete publication runs or qualification of
the current full catalog.

Observation construction serializes each input observation once and reuses the
bytes when assigning a new dictionary ID. SQLite replaces the unbounded Python
digest dictionary. Block compression fills one 1 MiB buffer at a time without
joining the complete logical block. The incremental reader uses maintained
[ijson](https://github.com/ICRAR/ijson), locked at 3.6.0, and validates part sizes,
array shape, counts and complete reads. Its default numeric mode preserves large
integers; decoded `Decimal` number tokens become floats only during canonical
comparison, matching the previous standard JSON float semantics. Source
`Decimal` values remain unsupported by the original deterministic serializer.
Split UTF-8, huge integers, negative zero, tiny/large floats and NaN refusal have
focused tests.

The observation-count handoff is an owned temporary file of unsigned 64-bit
counts, bound to the exact source reader. A complete row count and digest reject
missing, trailing or changed counts. Detail preparation consumes this file and
does not reopen reference sidecars for counts. Detail comparison streams one
canonical row and JSON fragment at a time rather than allocating complete batch
Python lists, JSON strings and encoded bytes. Repacking keeps Arrow comparison
independent of adaptive batch boundaries and coalesces admitted batches without
copying, up to the logical Arrow staging budget and requested output row-group size.
That staging metric is not a hard retained-buffer or process-memory ceiling.
Alias preparation now uses the same decode admission helper.

A budget refusal closes owned writers without flushing unfinished observations,
keeps the source and partial files for diagnosis, and writes
`preparation-memory-failure.json`; no publication manifest is accepted. Receipt
write failures become notes on the original error. A fresh output directory is
required for another build. Existing valid publications remain unchanged.

## Verification

Reproduce the bounded offline measurement with:

```sh
uv sync --locked
.venv/bin/python scripts/measure_preparation_decoded.py \
  --artifacts output/decoded-memory-recheck \
  --output docs/experiments/publication-remediation/evidence/decoded-memory.json
```

The measurement retains its source, successful outputs and explicit refusal
outputs when `--artifacts` names a fresh directory. Its 512 MiB ceiling uses a
50 ms `ps` watchdog and a final process high-water check, including native Arrow
allocations. This is an observed fixture ceiling, not an operating-system
allocation quota. The recorded receipt includes stage timings, Python peaks,
Arrow retained bytes, process memory, complete output digests, policy and decode
counts. The fixture exercises 12,004 source rows, a 6.29 MiB Arrow row, 10,000
observations on one row, 22,004 unique observation values, Unicode, duplicates,
nulls, empty values and a deliberate logical-value refusal. A separate
64 MiB repeated-string table expands from a small dictionary page: native reads
remain at most 128 rows, returned bytes split before admission, and a strict row
limit refuses before any Python conversion.

The isolated detail encoder comparison uses the same canonical bytes for both
arms. It measures intermediate Python allocation savings, not full preparation
speed. Streaming trades additional CPU work for lower allocation; the receipt
reports both timing and allocation. No fixture result is a full-catalog speedup,
production deployment, or diagnosis of an earlier out-of-memory failure.


The recorded final fixture peaked at **342,327,296 bytes** (accepted) and
**205,357,056 bytes** (refused), below the 536,870,912-byte ceiling. The dictionary
fixture returned at most 128 native rows / 8,389,120 Arrow bytes per decode;
ordinary admitted batches split below their 4 MiB budget. The separate oversized
6.29 MiB source row used the declared single-row path. All 18 sidecar parts were
decoded exactly once during observation verification, with 46,003 reference
lookups. The encoder-only Python peaks were 25,024,265 bytes versus 139,190 bytes,
with identical canonical-byte hashes; times were 0.0498 versus 0.1812 seconds.

The shared `ArrowStager` coalesces both detail and repack output. It checks logical
byte and row targets before aggregation, allows one admitted oversize row in its
own group, and retains native reads at 128 rows. Detail output on this fixture
fell from **101 groups / 237,429 bytes** before coalescing to **2 groups / 21,688
bytes**, with every ordered Arrow value equal. Detail staging recorded
3,581,789 logical bytes and 3,585,197 retained buffer bytes.
The receipt includes this comparison and the retained baseline artifact digest.
This corrects the intermediate small-group layout; full-catalog size, latency and
metadata costs remain unqualified.

Final integration used Python 3.12.13, PyArrow 25.0.1, ijson 3.6.0 (`yajl2_c`),
Node 22.22.2 and npm 11.19.1. `uv sync --locked` and
`npm ci --workspaces=false --engine-strict` completed. The focused Python suite
passed 235 tests; 100 maintained filename browser tests passed. The site built
29 pages from the pinned local review archive, and both real emitted bootstrap
smoke tests passed at `/congressional-tech/`, including the pinned deep link.
The browser smoke uses a Worker mock; full Python-to-browser values are covered
by the maintained filename reader tests. These are local verification results.

A further 60 publication custody/verification/CLI checks passed before the final
shared-runtime identity merge; the root integration run covers the combined
release. Raw final fixture and refusal outputs are retained in this worktree at
`output/decoded-memory-final8-20261018/` pending transfer before archive.

The final coalescing follow-up passed 80 focused detail/budget/observation/availability
checks and 100 maintained filename browser checks. It includes a stricter custom
row-byte limit boundary and writer-error propagation. The earlier 235-test run
remains the broader local baseline; the root integration run covers final combined code.
