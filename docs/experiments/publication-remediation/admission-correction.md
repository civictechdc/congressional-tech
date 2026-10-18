# Correct physical layout admission without relaxing record limits

The former 64 MiB row-group aggregate refusal rejected a retained valid catalog
layout before decoding any row. The rebuilt documents file has 1,024 rows in
group 389 and 163,912,431 total uncompressed column-chunk bytes. That total is
not a simultaneous allocation bound: it describes multiple encoded pages,
dictionaries and columns across many rows.

The correction uses selected chunk bytes only to plan the native batch size:

```text
max(1, min(requested_rows, 128, 4 MiB * group_rows // max(1, selected_chunk_bytes)))
```

The retained group shape plans **26 native rows**. Column selection follows
PyArrow's physical prefix rules: an exact path or a path followed by `.` matches;
overlapping prefixes count a chunk once; `None` selects all and `[]` selects none.
Empty metadata/data remains valid.

This arithmetic targets mean physical byte density. It is not an upper bound
on any row, batch, page, dictionary, retained buffer, or process memory. Actual
returned Arrow bytes and the container-aware Python estimate still split
batches or refuse a single oversized row before Python conversion. The 16 MiB
logical Arrow-row, 128 MiB row-estimate and 32 MiB JSON limits remain unchanged.
Full ordered Arrow comparison, exact observation reconstruction, schema/null/
duplicate/order handling and source-bound observation counts remain mandatory.
The obsolete aggregate limit is removed from the current policy and old
`validate_physical` callers are removed, rather than retained as a silent no-op.

Preparation uses one owned `Catalog` reader per original input. Repacking borrows
those exact reader objects and does not close them. Observations, details and
browse construction reuse them until the outer catalog closes. A standalone
repack path still owns its input reader; output verification readers remain
owned locally. This removes six redundant input footer opens: two aggregate
preflights, two repack source opens and two later source/document opens. A
pipeline regression observes only the independent manifest check plus the
catalog open per input, and checks the source/document reader pairing. Borrowed
reader tests cover success and readback failure; the owned output closes while
the original remains usable.

Preparation readers disable parallel prefetch (`pre_buffer=False`), use 64 KiB
buffered column reads and request `use_threads=False` for bounded batch loops.
Normal local search-reader options remain unchanged. These maintained PyArrow
options reduce avoidable readahead; they do not bound native page/dictionary
allocations. Dictionary-return types are unchanged and no dependency is added.

## Verification and qualification boundary

The tests cover the exact retained footer shape without decoding production
data, projection rules, empty/nonempty zero-column projection, planned native
calls, metadata/reader reuse, reader lifetimes and genuine Arrow/Python/JSON
oversized-record refusals. A generated one-column Parquet row group has more
than 64 MiB of uncompressed physical bytes but individually small Unicode rows;
repacking accepts it and completes full ordered value verification. Existing
semantic, publication, review, schema and browser-reader checks remain in use.

The unchanged 512 MiB adversarial fixture watchdog was run **once** for this
correction. Its source/failure files remain in
`output/admission-correction-fixture/` until transfer; the current receipt is
[evidence/admission-correction-memory.json](evidence/admission-correction-memory.json).
That fixture ceiling is not a production whole-catalog memory policy.

The earlier authorized real-data group-389 probe stopped at 556,236,800 sampled
RSS bytes before yielding a row. It was not repeated or enlarged. Row sizes and
native dictionary retention for the rebuilt full catalog therefore remain
unverified. This correction removes the known aggregate false refusal; it does
not claim that every real row passes the unchanged record limits or that a full
publication has completed. The normal authorized publication remains the
production observation point. No production network operation, publication,
workflow dispatch, push or resource-limit increase was performed here.

Local checks passed: **91** decoder/observation/detail/alias/recovery tests and
**142** focused publication/pair/viewer integration tests (overlapping coverage),
**17** browser catalog-reader tests, and the exact empty-group arithmetic edge.
The one unchanged fixture watchdog run peaked at **264,257,536 bytes** accepted
and **188,448,768 bytes** refused, below 536,870,912 bytes.
All 18 sidecar parts were decoded once; source hashes were preserved. Details
retained two groups / 21,688 bytes. Runtime and commands are in
[evidence/admission-correction-verification.json](evidence/admission-correction-verification.json).
Prior hosted success at `28360df` is recorded only as prior-revision context, not
evidence for this correction.
