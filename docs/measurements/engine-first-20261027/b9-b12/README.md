# Raw verification and old-index repair: local qualification

The original 17-case baseline is retained. The retroactive verifier/repair revision passes 38 focused local/native cases in 13.23 seconds on the approved `48636e5` runtime. The raw verifier and repair tool use native SQL for joins, conflict checks, observation ordering and Parquet outputs. A real local native fixture exercises the old selector's exact source TablePins, immutable earlier snapshots, multiple repair batches, body metadata and selector compare-and-swap. No live listing, body download, raw import or index repair ran.

The fixtures cover missing bodies; stored-size and ETag differences; mixed body and receipt-cleanup verification; null identities; conflicting digest evidence; original gzip files stored without transfer encoding; one LIST traversal; separate orphan output; deduplicated orphan/sample checks; exactly 25 sampled referenced bodies; interrupted listing; staged record tampering/collisions; exact stored-source restoration; binary hash types; explicit observation ordinals; and stale index selection.

Code review initially rejected verification-key filtering, null-key construction, premature digest filtering, observation ordering, binary coercion and repeated body-candidate identities. Contracts reproduced those failures before the fixes. That earlier rerun passed all 17 cases and its independent fix review approved those recorded revisions. The current retroactive changes await their own mandatory review. Architecture review also required an explicit orphan report. Results are in `orphans.parquet` and the `orphans` report count; previously verified orphans are not rehashed outside the sample.

These are fixture results on this Mac, not the first listing baseline or production resource qualification. Full-body reads occur only for the sample and bodies lacking both a capture reference and verification. There is no per-body HEAD. The selected old index is read through `release.dataset.groups.source` TablePins; application code never converts those rows into an intermediate export.

## Owner: first listing baseline and weekly verification

Use clean committed code, the old index runtime in `OLD_RUNTIME`, and the SQL-job runtime in `DOCSPEC_JOB_CONFIG`. The latter must support the selected source pins; live remote execution remains engine's C5 qualification. Maintenance, publish and backfill must not overlap. The old capture process may advance its selector; verification pins one selection before listing.

Provide complete local evidence inventories from the maintenance input stage. Each inventory is a JSON array of `{ "key": "raw/object/key", "path": "/absolute/local/file.jsonl.gz" }`. Receipts keep their real `receipts/...` keys. Verification files keep their `provenance/verification/...` keys and are gzip-packaged for the native JSON reader, including receipt-cleanup records. Empty history uses an empty gzip JSONL file. Input mirrors and inventories must correspond to the intended raw snapshot; this tool does not silently refresh an incomplete mirror.

`B9_WORK` must be a fresh durable directory. This first command reads live storage and is an owner gate:

```sh
.venv/bin/python -I -m congress_api.cli.raw_verify --bucket congressional-tech-raw --old-native-config "$OLD_RUNTIME" --engine-config "$DOCSPEC_JOB_CONFIG" --receipt-inventory "$RECEIPT_INVENTORY" --verification-inventory "$VERIFICATION_INVENTORY" --work "$B9_WORK"
```

Review `report.json`, `anomalies.parquet`, `orphans.parquet`, `digest-conflicts.parquet`, `measurement-conflicts.parquet`, `digest-repairs.parquet`, `unmeasured-digests.parquet` and the saved sample seed. A failed listing or content check produces no accepted baseline. `multipart` reports the actual count; compare it with the 61 known older bodies. A valid report pins the exact public verification bytes. This separate owner command creates them, without replacement:

```sh
.venv/bin/python -I -m congress_api.cli.raw_verify --bucket congressional-tech-raw --work "$B9_WORK" --apply-staged
```

The first baseline emits one fact for each listed body. Later runs append only newly listed baselines and this run's whole-read observations, including the fresh 25-body sample. Unchanged unsampled facts are not copied or assigned a new check time. Successful whole-read rows retain optional `stored_sha256`; an older true flag without that digest cannot qualify a stored-digest repair. A valid empty delta remains byte-pinned and apply is a checked no-op. Changed size or ETag remains a refusal, never an accepted update.

Repeat with a fresh work directory and current evidence inventories for each weekly check. Engine wires this component into maintenance and supplies pinned inputs/concurrency; release retention and lake-table drops belong to engine.

## Owner: temporary old-index repairs

B9's `capture_identity` pins the selected old index. `digest-repairs.parquet` carries an unambiguous receipt assertion joined to a successful whole-read measurement at an exact body/receipt/line/pointer locator. Measurement must match the current listed key, size and ETag, either from this run or prior accepted verification. Proposed, asserted and measured stored SHA must agree; measured size, time, ETag and evidence source travel with the repair. Receipt-only assertions remain explicitly unmeasured candidates and cause no extra GET. Contradictory measurements or assertions cannot enter repairs, even when the old index already equals the assertion. Missing evidence remains unknown; the tool does not substitute the original SHA-256, infer SHA-256 from an ETag, or start phase-2 rehashing.

Prepare and review a fresh repair stage:

```sh
.venv/bin/python -I -m congress_api.cli.raw_repair --old-native-config "$OLD_RUNTIME" --engine-config "$DOCSPEC_JOB_CONFIG" --repairs "$B9_WORK/digest-repairs.parquet" --expected "$CAPTURE_IDENTITY" --work "$B12_WORK"
```

The owner applies the pinned stage only after reviewing its native audit. A concurrent old capture selection causes refusal; retain the rejected stage and prepare against the new pin.

```sh
.venv/bin/python -I -m congress_api.cli.raw_repair --old-native-config "$OLD_RUNTIME" --expected "$CAPTURE_IDENTITY" --work "$B12_WORK" --apply
```

For an explicitly exported flat index, replace `--old-native-config` with `--captures "$CAPTURES_PARQUET"`; `--expected` is then that file's SHA-256. Flat repairs require an explicit Int64 `_capture_order`. Unordered flat inputs refuse rather than invent observation history. Fixed-width binary hashes and every unrelated field retain their types and values.

A missing old `.gz` body requires an exact retained stored copy. `RESTORE_INPUT` is a JSON array of `{ "key": "bodies/sha256/aa/<sha>.gz", "stored_path": "/owner/retained/exact.gz", "stored_sha256": "<stored-byte SHA-256>" }`. Establish that digest from existing receipt evidence or an explicit owner measurement; it is not the original-body digest. Preview and restore are separate commands:

```sh
.venv/bin/python -I -m congress_api.cli.raw_repair --restore-input "$RESTORE_INPUT"
.venv/bin/python -I -m congress_api.cli.raw_repair --restore-input "$RESTORE_INPUT" --bucket congressional-tech-raw --apply
```

Restoration verifies stored bytes and original content identity before a common create-only write. It never replaces an existing object. Run B9 again afterward. A missing exact copy or source time is an unresolved owner input, not permission to fabricate raw history. Local daily-capture regressions separately prove that creating receipts and index rows carry the actual stored-byte SHA-256 and size; a live daily run remains owner verification.

## Retroactive measurement and reuse evidence

The new contracts first reproduced 19 failures with 8 preservation checks passing (`0f50a23f`). Synthetic gzip fixtures compute their original/stored SHA, MD5 and sizes from actual bytes. They cover measured contradictions, failed-read exclusion, prior-proof admission, direct B9-to-B12 repair preparation, lost/conflicting proof, fixed binary types, native/flat ordering and compare-and-swap, weekly deltas, new unsampled baselines and empty apply. No live body read, network write or repair ran.

One 30-body fixture emits 30 first-baseline facts, then only 25 fresh sample facts in each unchanged week; a new unsampled referenced body adds one baseline without another GET. Full LIST/history comparison still runs; this is bounded history growth, not a production speed or memory claim.

The native receipt producer plan has one `StreamingTableExec` and one `UnnestExec` for concatenated captures and file references, preserving null/empty arrays and duplicate/null identity slots. `listed`, `index_refs`, `receipt_refs`, `verified` and `compared` are narrow materializations; downstream plans contain neither original receipt expansion nor prior-history windows. The final job reads only staged baseline/digest evidence and checked rows. Native result storage entries and producer/consumer EXPLAIN files are retained in `codex-raw/run2/verifier-fixes/native-plans/` in the implementation scratch; extra low-level scan execution counters are not exposed by this runtime.

The shared forced-view wrapper was removed. The proof-ingress predicate is materialized once as narrow scalar fields before grouping; this also avoids the runtime's common-expression nullability failure seen with the repeated aggregate-filter form. No engine code or resource limit changed.
