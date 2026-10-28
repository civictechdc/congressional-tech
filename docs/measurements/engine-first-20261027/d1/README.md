# Captures ingest: backfill and owner append

D1 reads qualified receipt files, or the pinned native typed/raw receipt counter, and writes the 34-column captures table through native jobs. The counter is receipt input; the old capture index is a comparison oracle only. The complete current transformation rules are `capture_comparison.RULES`; each comparison writes them to `comparison/comparison.json`, alongside full `old-only.parquet`, `new-only.parquet` and `changed-fields.parquet` evidence. Missing old rows and unexplained changes stop application for owner review.

The real vertical slice is `shared/raw-real-slice-1c3e131a`: 50 original receipt lines, 106 captures and 50 cached bodies. It is explicitly partial and must never be appended as a complete receipt population. Its public capture bytes rebuilt identically on engines `48636e5` and `9b59263`. The slice comparison matched all 106 rows with no old-only or new-only rows. It retains 41 changed rows for owner review: 19 context URL changes, 28 entry-time changes and one HTTP-status change, with overlapping counts. Their exact locators are in `codex-raw/run2/slice-9b59263/d1/comparison/owner-gates.json` in the protocol scratch. No comparison exception has been approved here.

The full-corpus backfill, full rebuild comparison and comparison against all 3,909,134 pinned old rows remain unfinished. The first real slice now passes the reader and canary. A complete receipt-key check containing the largest 187 MB line accepted 28 lines and 223 captures. A larger caption-key check refused its portable-batch limit before acceptance; its native scalar profile contains 910,574 rows with every measured string field at most 148 bytes. A tiny generic native materialization case reproduces that byte-limit boundary. The next full run waits for engine byte-fit qualification and a measured resource projection. These are local implementation checks, separate from the live owner append below.

## Qualified inputs

`RECEIPT_INVENTORY` is an explicit JSON list of receipt metadata objects with original `key` values and local `path` values for direct receipt inputs. Backfill discovery also supports non-date receipt segments through `--inventory-mode backfill`. Do not treat a subset of a receipt's lines as its complete population. `SOURCE_QUALIFICATIONS` explicitly maps every selected source path to its immutable creation or qualification manifest; direct receipt objects can instead carry their individual `qualification` path. A validated counter needs its own explicit binding. An authority supplies the source SHA-256 and size; custody checks refuse drift during execution. Input data and authorities must remain immutable.

The complete local staging and comparison command writes no live data. Use fresh work outside the checkout and the approved engine configuration:

```sh
.venv/bin/python -I -m congress_api.cli.captures_ingest \
  --receipt-inventory "$RECEIPT_INVENTORY" \
  --validated-counter "$VALIDATED_RECEIPT_COUNTER" \
  --source-qualifications "$SOURCE_QUALIFICATIONS" \
  --old-index "$PINNED_OLD_CAPTURE_INDEX" \
  --engine-config "$DOCSPEC_JOB_CONFIG" --work "$D1_BACKFILL_WORK"
```

For direct receipt inputs, omit `--validated-counter`. For incremental receipt selection, add `--existing "$PINNED_CAPTURES"`; the native selector excludes already ingested receipt keys before opening their payloads. The full oracle comparison belongs to the complete backfill, not an incremental subset compared with the entire old index.

## Owner: first live append

First finish full local qualification, resolve comparison gates, and qualify the Linux engine and explicit remote catalog authority. Supply credentials externally. From clean committed code, with a fresh work directory and the complete qualified backfill inputs, run:

```sh
.venv/bin/python -I -m congress_api.cli.captures_ingest \
  --receipt-inventory "$RECEIPT_INVENTORY" \
  --validated-counter "$VALIDATED_RECEIPT_COUNTER" \
  --source-qualifications "$SOURCE_QUALIFICATIONS" \
  --old-index "$PINNED_OLD_CAPTURE_INDEX" \
  --engine-config "$DOCSPEC_LIVE_JOB_CONFIG" --work "$D1_LIVE_APPEND_WORK" \
  --apply --table "$D1_VERSIONED_TABLE"
```

For a reviewed new table, add `--create-table --table-location "$REVIEWED_TABLE_URI"`; add `--create-namespace` only when the namespace is new. Remote execution omits `--catalog-root`; local catalog checks use an explicit local configuration and `--catalog-root "$LOCAL_CATALOG_ROOT"`. Native append replaces complete selected receipt keys and rejects stale catalog selections. No live lake write, raw import or capture ran during preparation.
