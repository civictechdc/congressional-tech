# Separate decode admission from writer retention

The first actual filename repack completed exact ordered equality but produced
777,356,470 bytes, 2,673 row groups and a 135,166,663-byte footer. Its closed
output and metadata remain under primary
`output/publication-remediation-20261018/rollout/local-current-catalog/trial-c8dda5d/`.
The writer used the 4 MiB logical decode-batch target as an output-group limit.
That also missed retained parent buffers: one admitted slice held 499,123,438
bytes and a staged table retained 486,852,980 bytes despite small logical data.
This was a layout and retention regression, not a failed exact-value check.

`DecodedPolicy.writer_buffer_bytes` now sets a separate **64 MiB** budget for
pending writer data. The 4 MiB ordinary decode target, 16 MiB logical row limit,
128 native rows, Python/JSON budgets and requested 8,192-row output maximum are
unchanged. A writer may combine multiple admitted batches while its retained
buffer sum and row count fit. Dense rows can fill the byte budget first.

Admission sums each pending batch's `get_total_buffer_size()`. This deliberately
overcounts shared buffers; it cannot undercount them. A batch retaining more
than twice its logical bytes and more than 64 KiB, or more than the writer
budget, is compacted using `pa.concat_arrays([column])`. PyArrow documents that
this operation copies array contents. The new record batch keeps its schema
and metadata. Its **actual** retained buffers are measured again: surviving
dictionary backing can still split a batch or explicitly refuse a single row.
No unbounded or handwritten writer is introduced.

Metrics distinguish incoming retained buffers, compacted buffers, conservative
pending bytes, logical staged bytes and deduplicated written-table buffers.
This budget bounds pending staging references, not all live process memory.
The native generator and recursive append frames can briefly retain old parents
alongside copies. Codec memory, metadata and temporary allocations remain
additional costs. This correction does not bound native dictionary/page
expansion or increase any infrastructure or browser cache.

## Bounded comparison and selected policy

The maintained experiment writes the same admitted stream to both 32 MiB and
64 MiB staging arms, then compares every selected source Arrow value, schema
and metadata against both complete outputs in order. Source custody is checked
before/after; it does not perform a new complete source hash. The real source
was the previously verified raw filename file, SHA-256
`2af2dbdb100fd0d9e96ae5af76ee22406a783944bdae0166869c44bb663fa174`.

One metadata open selected group 1052, the largest aggregate uncompressed
physical-chunk total (109,364,035 bytes), plus adjacent groups 1053–1059:
**8,192 rows**. The window was saved before decoding. Physical totals are a
selection proxy, not actual native decoded size; the test does not scan all
catalog values or necessarily encounter the largest native allocation.

| Declared stream | Writer budget | Groups | Footer bytes | File bytes | Maximum pending retained bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Synthetic 8,192 rows | 32 MiB | 2 | 937 | 1,361 | 33,287,420 |
| Synthetic 8,192 rows | 64 MiB | 1 | 753 | 975 | 57,578,240 |
| Retained groups 1052–1059 | 32 MiB | 6 | 386,690 | 4,723,450 | 33,454,091 |
| Retained groups 1052–1059 | 64 MiB | 3 | 241,517 | 4,443,476 | 66,556,260 |

Both arms preserve exact ordered values and schema. The retained test compacted
44 batches per arm; maximum incoming/native buffers were 69,049,693 bytes and
maximum compacted buffers were 3,964,518 bytes. Maximum admitted logical batch
size was 3,961,358 bytes. The dense retained stream still required three groups
with 64 MiB; it does not demonstrate that all groups reach 8,192 rows.

**64 MiB is the smallest tested budget** that filled an 8,192-row synthetic
group and improved the dense retained layout. It halves group count in the
retained sample and reduces that sample's footer by 37.54%. This is a bounded
sample result, not full-catalog size, speed, footer or browser qualification.
The measured arms explicitly override their writer budgets; the initial
measurement's default policy still says 32 MiB, before selecting 64 MiB.

The synthetic worker's sampled/high-water peak was 141,508,608 bytes under its
512 MiB ceiling. The one retained worker peaked at 1,104,068,608 bytes under the
authorized 7 GiB ceiling and completed in 3.59 seconds. Watchdogs sampled every
50 ms and checked final process high-water memory. No stopped probe was retried.

Focused checks passed **130** tests covering publication, decoding,
observations, details, aliases, recoveries and benchmark behavior. New cases
cover shared nested parents, Unicode/null/empty/duplicate/order and schema
preservation, dictionary backing surviving compaction, true row refusal,
independent decode/writer budgets and propagated copy/write failures without
flushing on abort. Exact records, commands and prior output metadata are in
[evidence/writer-staging.json](evidence/writer-staging.json).

The experiment helper is [measure_writer_staging.py](measure_writer_staging.py).
Owned raw outputs and progress remain in this worktree's
`output/writer-staging-synthetic/` and `output/writer-staging-retained/` pending
transfer. Complete retained-catalog preparation and closed-output browser
feasibility remain separate checks. No source acquisition, production action,
workflow dispatch, resource-limit increase, push or merge into main occurred.
