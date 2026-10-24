# Column types, normalization and VARIANT: data model review

Reviewed: `docs/engine-first-data-model.md` at `b4f0943f` (one entry for all formats, PDF first).
Lens: `parquet-optimization`, plus Iceberg type constraints. Versions read from the pinned
crates: parquet 58.4.0, iceberg 0.10.1, DataFusion 53.1.0, and hyparquet 1.31.2.

## Verdict

The model is already well normalized. Everything the pipeline filters, joins, sorts or acts on is
a native typed column. The only semi-structured parts are three "folds"
(`List<Struct<field, value>>`), and they hold display-only facts. There are no JSON-string
blobs in any Parquet file; JSON lives only in raw receipts and provenance, where it belongs.

Four things should change:
1. The lake column types use Arrow labels that Iceberg can't store.
2. One model rule reaches into a fold.
3. Two values the site code acts on are stuck in the `detail` fold.
4. A few dates are still strings.

VARIANT isn't usable yet.

## 1. Lake tables must use Iceberg types, not Arrow labels (correctness)

Iceberg 0.10.1's primitive types are `boolean`, `int`, `long`, `float`, `double`, `decimal`,
`date`, `time`, `timestamp`, `timestamptz`, `timestamp_ns`, `timestamptz_ns`, `string`, `uuid`,
`fixed(L)` and `binary` (`iceberg-0.10.1/src/spec/datatypes.rs:212-249`).
- There is no 16-bit integer. The docspec writer silently widens `Int16` to `Int32`
  (`docspec-rs/src/storage.rs` compatible casts).
- There is no dictionary type. The writer doesn't convert Arrow `Dictionary` arrays, so a
  `dict`-typed batch would fail its schema match.

Write the lake schemas in Iceberg types; dictionary encoding is a Parquet writer setting (on by
default), not a type:

| Data model says | Lake (Iceberg type → Parquet physical) | Release files (Arrow → Parquet) |
|---|---|---|
| `dict` | `string` → BYTE_ARRAY UTF8, dictionary-encoded by the writer | `Utf8` (dictionary-encoded by the writer); no Arrow `Dictionary` type needed |
| `int16` (`http_status`, `congress`, `last_status`) | `int` → INT32 | `Int16` → INT32 with the INT(16) annotation; hyparquet reads a number |
| `int32` | `int` → INT32 | `Int32` |
| `int64` (`bytes`, `stored_bytes`, `h_content_length`) | `long` → INT64 | `Int64` |
| `ts` | `timestamptz` → INT64 TIMESTAMP(MICROS, UTC) | `Timestamp(us, "UTC")`; hyparquet returns a `Date` |
| `date32` | `date` → INT32 DATE | `Date32` |
| `fsb(32)` (sha256, `fingerprint`, ids) | `fixed[32]` → FIXED_LEN_BYTE_ARRAY(32) | `FixedSizeBinary(32)` |
| `fsb(16)` (`stored_md5`) | `fixed[16]` | — |
| `fsb(8)` (`link_key`) | — | `FixedSizeBinary(8)`. Keep it, not INT64: its byte order matches the hex order of the public key, and hyparquet compares FLBA bytes unsigned. A signed INT64 would misorder keys with the high bit set and break page pruning. |
| `list<dict>` (`error_signals`) | `list<string>` | — |
| fold | `list<struct<field: string, value: string>>` | same |

Measured earlier: dictionary vs plain made no difference for `captures.sha256` (48–50 MB either
way; ZSTD absorbs the repeats), so the lake needs no per-column encoding tuning. Keep per-column
tuning to the browser files (`list.filename` with `DELTA_BYTE_ARRAY`, already adopted).

## 2. Normalization: native vs folded

**Rule:** a value is a native typed column if anything filters, joins, sorts or computes on it,
or if the site's code acts on it. A value goes in a fold only if it is sparse and only ever
displayed.

| Place | What the model does with it | Verdict |
|---|---|---|
| `captures` | All line and capture fields native; header allowlist as `h_*` columns; recovery fields native | ✓ |
| `readings` core (`format`, `record_role`, `title`, `heading`, `text_bytes`, `error_signals`, `fingerprint`) | Used by the real-file rule | ✓ |
| `readings.fields` fold | **§3.1 derives `record_role` "from format and the reading", including "MODS/PREMIS/meeting/witness XML roots"**. The XML root sits in the fold, so the model would unnest the fold to classify documents. | **Fix:** the parser writes `record_role` (already a native column) and an `xml_root` string column. The model reads those and never reaches into `fields`. |
| `filename_readings` | Facets native (`document_kind`, `document_family`, `committee_code`, `congress`, `date_token`, `measure_*`); about 106 sparse display fields in the fold | ✓ |
| `page_links` | Native `parent_url`, `child_url`, `text`, `source_xpath`, `doc_type`; `add_date` and `publish_date` are strings | Keep the publisher's strings in the lake (raw wording); the model parses them to `date32` for `occurrences.add_date`. Unparseable becomes null. |
| `captures.h_last_modified` | string | Parse to `timestamptz` in the lake. Raw text stays in receipts. |
| `captures.pointer` | JSON-path string, "informative" | Keep as a string; nothing reads it, and it's cheap with ZSTD. |
| `detail` typed core | `document_id`, `occ_start`, `occ_len`, `recoveries`, `alternates` | ✓ |
| `detail` fold | Contains `link_key` and `saved_key`, which the **site code acts on**: building the shareable link and the download URL | **Fix:** move `link_key` (`FixedSizeBinary(8)`) and `saved_key` (`Utf8`) to the typed core. That adds 2 leaves, about 10 concurrent page reads per view instead of 8. Keep `source_url`, dates, `date_kind`, `member_count`, `r.*` and `f.*` in the fold, as display-only. Write dates in the fold as ISO `YYYY-MM-DD` so they sort and parse cleanly. |
| `occurrences` | Specified without types | `list_row Int32`, `ordinal Int16`, `url Utf8`, `member_path Utf8`, `filename Utf8`, `first_fetched` and `last_fetched` `Date32`, `outcome Utf8`, `is_saved Boolean`, `linked_from Utf8`, `link_text Utf8`, `doc_type Utf8`, `add_date Date32` |
| `url_state` (release) | `requested_url Utf8`, `attempts Int32`, `last_attempt` and `next_attempt_at` `Timestamp(us, UTC)`, `last_status Int16`, `last_outcome Utf8`, `links_scanned Boolean` | ✓ as specified |

Raw receipt fields with no lake column (`redirects`, `source_context.observations`, `writer`)
are fine, since nothing in the model reads them. Invariant 3 ("every line carries `writer`")
should then be checked against receipts, not the lake. Or add `writer_commit` and `writer_job`
as `string` columns, which are constant per run and so cost nothing under RLE.

## 3. Folds vs `MAP` vs `VARIANT`

| Option | Fit |
|---|---|
| Fold `list<struct<field, value>>` | Flat (one repetition level), ordered, and the field name dictionary-encodes to almost nothing. Works in Iceberg, DataFusion (`unnest`) and hyparquet. **Keep.** |
| `map<string, list<string>>` | Same information, but two nesting levels (more definition and repetition levels) and no ordering. No gain. |
| `VARIANT` (Parquet logical type; Iceberg v3 `variant`) | Typed semi-structured values, with optional "shredding" of hot fields into real columns. **Not usable in this stack today:** iceberg-rust 0.10.1 has no variant type, so it can't be used in any lake table; parquet-rs 58.4 reads and writes it only behind the `variant_experimental` feature (`parquet-58.4.0/Cargo.toml:73-92`), which docspec doesn't enable; DataFusion 53 has no variant functions. hyparquet 1.31.2 does decode it (`src/variant.js`), so release files could carry it, but the fold values are short display strings that are read whole, so there would be no measurable gain. |

**Recommendation:** no VARIANT now. The fold plus native hot fields is already "manual
shredding". Revisit when iceberg-rust supports v3 `variant` and DataFusion has variant
functions. At that point `readings.fields` and `filename_readings.fields` are the candidates,
because typed values (dates, numbers) would stop being strings.

## house-naming metadata: VARIANT or not (owner decision, 2026-10-24)

Measured on 5,000 random real filenames with house-naming 3.2.7 (0.38 ms per file):
- `metadata` is flat (164 distinct fields, median 2 values per file, p90 17).
- **0 non-string values**: house-naming keeps literal source text by design.
- Storage: the field/value fold is 16.4 B per file; a per-row JSON column (a stand-in for
  unshredded VARIANT, which also carries field names in every row) is 15.3 B per file. ZSTD
  absorbs the repeated names.
- The `observations` ("why" evidence) have a fixed 12-key schema. As typed nested Parquet they
  are 39 B per file, about 55 MB per catalog version. Whether to keep them is still open with
  the owner.

**Decision:** keep the typed facets plus the field/value fold for `filename_readings.fields`.
Not VARIANT today, because iceberg-rust 0.10.1 can't store it; and not after a stack upgrade
either, because the data is flat strings, the hot fields are already native, the size is the
same, and it would cost an Iceberg v3 upgrade. VARIANT's real candidates here are genuinely
nested, mixed-type sources (Congress.gov API JSON, MODS and meeting XML trees), if they are ever
made queryable in the lake.
