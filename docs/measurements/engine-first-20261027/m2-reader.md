# M2 receipt reader: local preparation evidence

M2 remains **partly done**, with no receipt-mapping, resource, step-form or graph verdict. The complete cleaned scratch inventory is readable and retained in a DataFusion Parquet stage. The draft expansion differs from the pinned capture index by 285 rows; that difference remains unexplained until the per-line comparison and mapping audit finish.

This is a Mac mechanism run using Cargo's default development build, not an optimized measurement on the required four-CPU, 16 GB Linux runner. Use an optimized build and an otherwise idle specified runner for accepted comparisons. The values below describe the actual local attempts; they do not replace PLAN §5.2's decision rule.

| Observation | Result |
|---|---:|
| Receipts / JSON lines | 2,289 / 2,596,054 |
| Original line bytes retained in the stage | 13,407,457,961 |
| Largest line / captures on that line | 187,661,340 bytes / 196 |
| Largest capture list on any line | 5,806 |
| Draft capture-expansion population | 3,908,849 |
| Pinned old capture index | 3,909,134 |
| Diagnostic field-path occurrences / largest per line | 306,686,965 / 8,628,201 |
| Complete typed/raw/census stage | 1,656,781,104 bytes |
| Complete stage time / observed peak RSS | 426.64 s / 6,375,964,672 bytes |
| Subsequent three-query count/shape/locator pass | 155.80 s / 11,184,635,904 bytes |
| Spill observed in either successful run | 0 |

The source is B0's fully verified cleaned scratch mirror, pinned before the first read by protocol `3fd6cbb8`. Its 2,289-file identities and cleanup invariants are in the B0 report; the real cache remains unchanged. The schema is supplied by the application. Arrow JSON decodes nullable fields with type-conflict nulling; each original UTF-8 line, one-based locator, family/shape and field-path evidence is retained. Three scratch contract tests pass for conflicts/raw fallback, sanitized malformed-input locators and capacity/schema/key refusals.

Four sequential file groups bound the source to one open receipt per group, rather than queueing a batch for every receipt. Chunks are at most 64 lines or 8 MiB, except one line may reach the explicit 512 MiB allowance. The candidate reserves six times each admitted chunk's bytes before typed decoding, using the shared 10 GiB pool. The external owned-process observer samples RSS and scratch every 200 ms, stopping at 14 GiB RSS or 32 GiB scratch. Sampling and the six-times estimate do not prove instantaneous memory bounds. Native Parquet/Arrow allocations explain why RSS is recorded separately from pool use.

The census currently visits all nested values and serializes their normalized field paths, including repeated array paths. Its cost is linear in visited values times path depth; the 306 million repeated path occurrences are diagnostic overhead, not needed by the production reader. The retained stage allows field-presence deduplication, mapping work and the capture-index comparison through SQL without rereading gzip inputs. No conflict or shape may be silently omitted from that audit.

Rejected preparations remain in scratch. The first export refused the incomplete `zstd` option before reading data; the explicit level is `zstd(3)`. The next export hit Parquet's 32,767-row-group file limit at 64 rows per group: 158.37 seconds and 8,618,835,968 bytes observed RSS, with an unadmitted partial output. One second of focused parser tests overlapped that rejected run, so its timing is not a controlled trial. The successful export used 256-row groups; it ran without other builds or tests. A one-second process sample inspected its long tail and found census traversal and Parquet writing active. Keep the failed outputs and logs; they are not valid input stages.

Source SHA-256 pins are in `m2-reader-pins.json`. Detailed jobs, full plans, logs, resource observations, the raw-preserving stage and rejected artifacts stay in scratch as `cx_m2_receipt_*` and `cx_m2_stage_counts*`. Next: full field census, per-file conflicts, the 285-row comparison, isolated largest-line resources, S1 links, all joins/build sizes, named versus inline trials and graph labels/refusal. The Linux check cannot run on this Mac, Docker is excluded, and no remote workflow is authorized.
