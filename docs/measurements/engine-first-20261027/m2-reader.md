# M2 receipt reader: local preparation evidence

M2 remains **partly done**, with no receipt-mapping, resource, step-form or graph verdict. The complete cleaned scratch inventory is readable and retained in a DataFusion Parquet stage. All 285 row-count differences are now explained: each line records one identical body, context, size and time in both `captures[]` and `file_references[]`; the old index kept both. The intended expansion keeps one row. Every secondary entry also holds a stored size missing from its primary entry, which the mapping must retain. Exact per-file conflict counts are now retained; full field mapping remains unqualified.

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

Rejected preparations remain in scratch. The first export refused the incomplete `zstd` option before reading data; the explicit level is `zstd(3)`. The next export hit Parquet's 32,767-row-group file limit at 64 rows per group: 158.37 seconds and 8,618,835,968 bytes observed RSS, the native writer removed its partial output on failure. Its job, log and resource observations remain retained. One second of focused parser tests overlapped that rejected run, so its timing is not a controlled trial. The successful export used 256-row groups; it ran without other builds or tests. A one-second process sample inspected its long tail and found census traversal and Parquet writing active. The rejected jobs produced no valid input stage; retained logs record their refusals.

Source SHA-256 pins are in `m2-reader-pins.json`. Detailed jobs, full plans, logs, resource observations, the raw-preserving stage and rejected artifacts stay in scratch as `cx_m2_receipt_*` and `cx_m2_stage_counts*`. The committed `m2/` directory holds the complete field-presence census: 1,547,462 family/shape/field-kind rows, 21 families and 37 family/shape combinations, plus the 193 mode/status/outcome combinations and a field-family summary. Dynamic source dictionaries account for many distinct paths, including YouTube video maps, package-location maps and provider searches; these are not millions of native lake columns. Each line counts once per field-kind presence. The analysis took 334.06 seconds, peaking at 13,642,088,448 bytes observed RSS with 168,023,264 bytes logical spill; the footprint is close to the runner budget and remains unqualified there. Checks of all 285 pairs pass (`cx_m2_verified_gap_report.json`), and DM plus fixture `7255d399` require storage-field preservation and unmatched-secondary refusal.

The current S1 page parser also completed all 3,425 locally available bodies without a rejection, reading 397,586,443 bytes and retaining 303,064 literal links and 3,424 fingerprints; 3,045 candidates remain unavailable. This current-source replay replaces the prototype facts for subsequent link experiments.

The exact conflict audit follows fixture `a1487e82`: it compares actual Arrow nulls with non-null source values, including parent structs and list positions, and ignores absent or explicitly null fields. Four scratch tests pass. The reader releases its typed-decoder tape before the diagnostic JSON pass, avoiding simultaneous parser scratch. It still retains the original bytes and unchanged field census.

The complete counter-equipped export took 447.16 seconds, with 6,243,155,968 bytes OS-reported maximum RSS. The observer now also includes all named M2 staging and retained artifacts in its disk guard: peak allocated scratch was 3,834,351,616 bytes. The isolated first line of the House XML receipt is exactly 187,661,340 bytes with 196 captures and zero conflicts; it took 33.76 seconds and 2,677,981,184 bytes observed RSS. These remain development-build Mac observations.

The full audit finds **355,250 nulled values on 355,250 lines**: 354,555 at `record.family`, 569 at `record.source_associations`, 99 whole list-valued `record` objects, and 27 at `record.http_status`. Counts by every receipt and every exact JSON path are committed under `m2/`, with the new source/binary pins in its manifest. These are schema conflicts, not discarded raw data or accepted application interpretations. The mapping must use the raw fallback or a documented shape-specific source rather than stringify a conflicting object.

An independent DataFusion SHA-256 comparison joins only receipt/line keys and 32-byte hashes: **zero changed or missing raw lines** across all 2,596,054 rows. Its complete count/conflict/hash analysis took 494.43 seconds and 11,485,380,608 bytes observed RSS. No raw string entered that hash-join build.

Next: complete ingest fields and fallback samples, S1 links, all joins/build sizes, named versus inline trials and graph labels/refusal. The Linux check cannot run on this Mac, Docker is excluded, and no remote workflow is authorized.
