# Captures ingest: backfill and owner append

D1 reads qualified receipt files, or the pinned native typed/raw receipt counter, and writes the 34-column captures table through native jobs. The counter is receipt input; the old capture index is a comparison oracle only. The complete current transformation rules are `capture_comparison.RULES`; each comparison writes them to `comparison/comparison.json`, alongside full `old-only.parquet`, `new-only.parquet` and `changed-fields.parquet` evidence. Missing old rows and unexplained changes stop application for owner review.

The real vertical slice is `shared/raw-real-slice-1c3e131a`: 50 original receipt lines, 106 captures and 50 cached bodies. It is explicitly partial and must never be appended as a complete receipt population. Its public capture bytes rebuilt identically on engines `48636e5` and `9b59263`. The slice comparison matched all 106 rows with no old-only or new-only rows. It retains 41 changed rows for owner review: 19 context URL changes, 28 entry-time changes and one HTTP-status change, with overlapping counts. Their exact locators are in `codex-raw/run2/slice-9b59263/d1/comparison/owner-gates.json` in the protocol scratch. No comparison exception has been approved here.

The full-corpus backfill, approximately 200-receipt rebuild proof and comparison against all 3,909,134 pinned old rows remain unfinished. The owner replaced the one-shot full run with bounded whole-receipt batches through the same incremental CLI. Each batch retains the existing private receipt checks; one final native job checks the complete public table. The independent source-count report is a required input and remains unqualified. No downstream reader may treat a batch report alone as completed acceptance.

## Qualified inputs

`RECEIPT_INVENTORY` is an explicit JSON list of receipt metadata objects with original `key` values and local `path` values for direct receipt inputs. Backfill discovery also supports non-date receipt segments through `--inventory-mode backfill`. Do not treat a subset of a receipt's lines as its complete population. `SOURCE_QUALIFICATIONS` explicitly maps every selected source path to its immutable creation or qualification manifest; direct receipt objects can instead carry their individual `qualification` path. A validated counter needs its own explicit binding. An authority supplies the source SHA-256 and size; custody checks refuse drift during execution. Input data and authorities must remain immutable.

`SOURCE_COUNTS` is an independently produced JSON list with one row per receipt: `key`, `source_rows`, `uncompressed_bytes`, `list_items`, `expected_captures`, `max_line_bytes`, and `max_line_items`. Its exact key set must equal the pinned inventory. Complete accepted direct-source stages can be named by `prepared_stage` instead of `path`; their mapping must match the current code. Batch targets never split a receipt or weaken its physical memory ceiling.

## Local proof and backfill

These commands write only to a fresh unpublished local generation. Use a pinned runtime with at most four compute threads (two for the heaviest batches), approximately 10 GiB native memory, and the maintained 16 GiB physical-footprint monitor. Set `OWNED_SCRATCH` to contain the work, local catalog and table locations; the driver checks its allocated bytes against 5 GiB and requires at least 15 GiB free disk. A new work directory is required on every invocation. One writer runs at a time.

Plan without opening receipt payloads:

```sh
.venv/bin/python -I -m congress_api.cli.captures_ingest \
  --backfill --source-counts "$SOURCE_COUNTS" \
  --receipt-inventory "$RECEIPT_INVENTORY" \
  --engine-config "$DOCSPEC_JOB_CONFIG" --work "$D1_PLAN_WORK"
```

Prove one-shot and batched equality over about 200 original receipts, including the largest lines. The CLI creates separate generation names and compares all 34 public columns with native `EXCEPT` in both directions:

```sh
.venv/bin/python -I -m congress_api.cli.captures_ingest \
  --backfill --prove-equivalence --source-counts "$SOURCE_COUNTS" \
  --receipt-inventory "$RECEIPT_INVENTORY" \
  --validated-counter "$VALIDATED_RECEIPT_COUNTER" \
  --source-qualifications "$SOURCE_QUALIFICATIONS" \
  --engine-config "$DOCSPEC_JOB_CONFIG" --work "$D1_PROOF_WORK" \
  --catalog-root "$LOCAL_CATALOG_ROOT" --table "$D1_VERSIONED_TABLE" \
  --table-location "$D1_LOCAL_TABLE" --scratch-root "$OWNED_SCRATCH"
```

Then populate the fresh unpublished generation:

```sh
.venv/bin/python -I -m congress_api.cli.captures_ingest \
  --backfill --source-counts "$SOURCE_COUNTS" \
  --receipt-inventory "$RECEIPT_INVENTORY" \
  --validated-counter "$VALIDATED_RECEIPT_COUNTER" \
  --source-qualifications "$SOURCE_QUALIFICATIONS" \
  --engine-config "$DOCSPEC_JOB_CONFIG" --work "$D1_BACKFILL_WORK" \
  --apply --catalog-root "$LOCAL_CATALOG_ROOT" --table "$D1_VERSIONED_TABLE" \
  --create-table --create-namespace --table-location "$D1_LOCAL_TABLE" \
  --scratch-root "$OWNED_SCRATCH"
```

Omit `--create-namespace` when the namespace exists. After a lost acknowledgment, repeat with a fresh work directory and omit both create flags. Fresh native heads decide which complete receipt keys to skip before source admission. Keep the retained batch evidence for the old-index comparison; never regenerate it by rereading raw solely for comparison.

The final `public_guard_passed` report proves the public checks and exact independent per-receipt counts. `qualified_for_downstream` deliberately remains false: the caller must also retain the successful rebuild proof, review the complete old-index comparison and its owner gates, and record native file and manifest counts against the maintenance threshold. The old comparison covers the original 2,289 receipt keys; the three later qualified receipts are reported separately.

## Owner: first live append

Finish the local acceptance checks, resolve comparison gates, and qualify the Linux engine and explicit remote catalog authority first. Supply credentials externally. From clean committed code and a fresh work directory, the owner runs the same bounded path:

```sh
.venv/bin/python -I -m congress_api.cli.captures_ingest \
  --backfill --source-counts "$SOURCE_COUNTS" \
  --receipt-inventory "$RECEIPT_INVENTORY" \
  --validated-counter "$VALIDATED_RECEIPT_COUNTER" \
  --source-qualifications "$SOURCE_QUALIFICATIONS" \
  --engine-config "$DOCSPEC_LIVE_JOB_CONFIG" --work "$D1_LIVE_APPEND_WORK" \
  --apply --table "$D1_VERSIONED_TABLE" --scratch-root "$OWNED_SCRATCH"
```

For a reviewed new table, add `--create-table --table-location "$REVIEWED_TABLE_URI"`; add `--create-namespace` only when the namespace is new. Remote execution omits `--catalog-root`. Native append replaces complete selected receipt keys and rejects stale catalog selections. No live lake write, raw import or capture ran during preparation.
