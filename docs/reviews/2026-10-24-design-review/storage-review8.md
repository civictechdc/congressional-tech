# Review 8: storage, engine and determinism (engine-first-data-model.md @ 33c2cba0)

## 1. Score

**71 / 100. Confidence: medium.**

The document does most of the hard determinism work. Export sort keys are unique by construction: `list` ends in `document_id`, every other release order ends in a unique key, and the `members`, `sources` and `recoveries` orders are total. Hash inputs are defined as one byte-exact encoding (§3, compact JSON), and that encoding matches both Python and serde_json, which I verified. Lake PKs are non-null, so they can be identifier fields. Completion rows close the "no output" hole. Truncated keys are protected by a collision refusal. The reference inputs are pinned by generation digest. Release sizes I could measure agree with the estimates.

Points come off for three reasons:
- Several rules require engine features that the pinned engine (docspec-rs d9c6719, DataFusion 53.1.0, iceberg 0.10.1, parquet 58.4.0) does not have. One of them, a compact-JSON encoder, is not even listed among the engine capabilities ARCHITECTURE §13 requires.
- The bytes of a release depend on engine limits that the profile does not pin.
- A few picks inside the model have no total order, and that is exactly the kind of gap that breaks byte-identity across thread counts.

Confidence is medium: I read the engine code but did not execute it.

## 2. Findings (most severe first)

### F1. Major: the ID and URL rules need SQL functions that neither DataFusion 53.1 nor docspec-rs provides, and the compact-JSON encoder is not in ARCHITECTURE §13 at all
**Where:** §3 l.84–85 (compact JSON); §7.4 l.558 (`source_id`); §7.5 l.633–641 (`document_id`, `version_keys`); §7.11 l.759–760 (`witness_key`); §7.2 l.461–479 (`url_key`, `unwrap`, reference resolution); §7.5 l.608 (ConnectedComponents).

**Problem:**
- Four IDs hash compact JSON built from arbitrary filenames and URLs. Building that JSON in SQL needs a JSON string escaper, and nothing provides one.
- `url_key` needs RFC 3986 resolution and percent-encoding normalization. ARCHITECTURE §13.8 lists these as required, but they do not exist yet.
- The engine's connected components cannot run inside the one job as §7 describes:
  - it accepts only a pinned dataset release as input, not an in-job relation;
  - its keys and edges must be Utf8, not `fsb(32)`;
  - it computes `document_id` itself, which puts ID policy inside the engine. ARCHITECTURE §13 forbids that.

**Evidence:**
- DataFusion: `datafusion-functions-53.1.0/src/{string,unicode,crypto,encoding}` has `sha256` and hex/base64 `encode`/`decode`. It has no `to_json`, no JSON escaping, no NFKC and no URL functions. A grep for `to_json|json_escape|nfkc` found nothing relevant.
- docspec-rs: `grep ScalarUDF|create_udf|fn name(&self)` in `src/` finds only two UDAFs (`engine/aggregation/udaf.rs:98,336`) and one window UDF (`comparison/window.rs:129`).
- `src/engine/connected_components.rs:93-124`: `register_input` reads `spec.input.dataset` from the release pins.
- `connected_components.rs:135-155`: refuses any row_key or edge that is not Utf8.
- `connected_components.rs:27-36`: `compute_document_id` serializes `("bodies", list)`.

**Verified:** yes, by code reading. Not executed.

**Fix:** rewrite §3 "compact JSON" so it names the producer: "…This is the output of the engine's `json_array(...)` SQL function, whose golden vectors equal Python's `json.dumps(…)`." Then add that function to ARCHITECTURE §13.8 beside the URL functions. In §7.5, rewrite `components` to "ConnectedComponents over Utf8 hex node keys, run as a materialized step of the job; it returns only a component number, and the model computes `document_id` in SQL."

### F2. Major: release bytes depend on engine limits the profile does not pin, and the export does not yet re-batch or flush on row count
**Where:** §7.1 l.418 (what the profile pins); §8.1 l.797–802 (writer settings and profiles); invariant 4 l.900.

**Problem:**
- The export writes DataFusion's batches as they arrive.
- It flushes a row group when either the writer's memory or the encoded bytes cross a threshold, not only when the row count is reached.
- parquet-rs starts its page-limit chunking afresh on each `write()` call. Page and row-group boundaries therefore follow the upstream batch sizes, which depend on `batch_rows`, `compute_threads` (`target_partitions`) and `max_batch_bytes`.
- These are runner configuration (`Limits`). Neither the model profile nor the input identity includes them.
- The export settings also differ from §8.1 throughout:
  - dictionary is enabled on every column;
  - data pages are 1 MiB, and 16 KiB only on page-index columns;
  - the write batch is 256 rows;
  - there is no `data_page_row_count_limit` and no per-column encoding.

**Evidence:**
- `src/engine/export/pipeline.rs:556-596`: no re-batch; sub-batches are sliced only at the row-group limit.
- `pipeline.rs:610-613`: `memory_size() >= max_batch_bytes || in_progress_size() >= max_row_group_bytes`.
- `pipeline.rs:676-698`: the writer properties listed above.
- `src/budget.rs:36-47`: defaults of 12 threads, `batch_rows` 8192 and `max_batch_bytes` 64 MiB.
- `budget.rs:116-121`: wires these into `SessionConfig`.

**Verified:** by code reading. The byte drift across thread counts is inferred, not executed.

**Fix:** in §7.1, rewrite the "It pins" bullet to read "…the engine revision **and its execution limits (threads, batch rows, batch bytes)**, …", so the drift is at least pinned until the engine meets ARCHITECTURE §10.2. Keep §8.1 as written; it is the right target. The determinism test (ARCHITECTURE §15.4) must gate the engine upgrade.

### F3. Major: some picks inside the model have no total order
**Where:**
- §7.5 l.676–677 `committee_name` ("the name … history gives for the document's date");
- l.678–680 `govinfo_package_id` ("the package ID in **a** member source file's source URL");
- l.611–613 saved-file order ("exact-bytes before other fidelity", where `fidelity` belongs to a capture row but a source file can have several);
- l.564 `first_fetched`/`last_fetched` (over all fetch rows or only good fetches?);
- §7.10 l.742 with §7.2 l.483 (a repaired `href` split into several links shares one link index).

**Problem:** where the input has ties, each of these becomes `first_value` or `any` without an ORDER BY. Results can then differ between runs and thread counts. The export's unique-sort-key check never sees this, because it checks only the final sort.

**Evidence:** the pinned `committees` generation (`generations/committee-rosters/5f03…/committees.parquet`) has **12 overlapping pairs of different `officialName` intervals within one `system_code`**. One example: `ssaf14` has "Subcommittee on Conservation, Forestry, and Natural Resources" over 2011-04-06 to 2024-05-13, overlapping "Senate Subcommittee on Conservation, Climate, Forestry…" over 2021-01-03 to 2024-12-09. Script: `r8s_overlap.py`, `r8s_reftypes.py`.

**Verified:** yes for committee names. The others are textual.

**Fix:** rewrite each rule with its tie-break:
- `committee_name`: "…the history entry whose interval holds the date, latest `startDate` first, then `officialName` bytewise…".
- `govinfo_package_id`: "the package ID of the first member source file in the saved-file order whose source URL holds one, else…".
- Saved-file order: "exact-bytes when any of its capture rows is exact-bytes".
- `first_fetched`/`last_fetched`: "over its good fetches (§7.3) outside import runs".
- Link index: "link index, then split position".

### F4. Major: `url_state.next_attempt_at` can depend on when the job runs
**Where:** §7.1 l.449 ("age bands where pages change with a meeting's age"); §7.7 l.705–708.

**Problem:** the rule does not say what the age is measured against, or which meeting a requested URL belongs to. Measuring against the publish clock would:
- break byte-identity (ARCHITECTURE §10.2: "no timestamps or run-specific values"), and
- make the early skip (ARCHITECTURE §10.3.2) skip a release whose content would have changed.

**Verified:** textual.

**Fix:** rewrite the l.449 row's Holds cell as "`(family, interval)`, with age bands keyed on `last_attempt − meeting_date` of the URL's `file_meetings` (§7.5), earliest meeting first". Rewrite l.707 as "…plus the interval for that age at `last_attempt`".

### F5. Minor: converting timestamps to dates has no stated time zone, and the spicy-regs dates are UTC instants of Eastern midnight
**Where:** §4 l.91; §7.5 l.628–629, l.693; §7.10 l.739; §8.1 l.812, 815–818.

**Problem:**
- `first_captured`, `first_seen`, `imported_at` and `review_decided_at` are `ts` values published as `date32`. A capture between 8 pm and midnight Eastern lands on the next UTC day.
- The spicy-regs date columns are VARCHAR (`introduced_date`, `term_start`, `pub_date`, history `startDate`/`endDate`). History values look like `1974-07-12T04:00:00Z` and `1977-02-04T04:59:00Z`, where 1,606 of 1,839 history dates fall at 04:xx or 05:xx UTC.
- A UTC cast of an `endDate` at `T04:59Z` yields the next day, so both names apply on the boundary day.

**Evidence:** pub.json column types; `r8s_reftypes.py`, `r8s_overlap.py`.

**Verified:** yes for the reference data.

**Fix:** rewrite §4's `date32` definition as "a day-precision date; a `ts` becomes a `date32` in America/New_York (tz database pinned with the engine), and a spicy-regs instant likewise".

### F6. Minor: hashes are "binary everywhere" except where the doc makes them hex strings, and the same key has two types across release files
**Where:**
- §4 l.97 says hashes are binary.
- §7.5 l.639–641: `version_keys` are "the hex of the first 8 bytes".
- §7.11 l.759: `witness_key` gives no encoding.
- §8.1 l.814: `witness_key` is `fsb(8)`.
- l.826: `list.witness_keys` and `version_keys` are `List<dict>` strings.

**Problem:** invariant 16 joins `list.witness_keys` to `witnesses.witness_key` across two types.

**Verified:** textual.

**Fix:** rewrite §4 l.97 as "Hashes are binary (`fixed[32]`, `fixed[16]`, `fsb(32)`, `fsb(8)`) except keys held in `List<dict>` key columns of `list`, which are lowercase hex of the same bytes". In §8.1, make `witnesses.witness_key` `dict` (hex) to match.

### F7. Minor: the §6 lake writer settings cannot be enforced, and they claim effects iceberg-rust does not deliver
**Where:** §6 l.201–203.

**Problem:**
- The engine's lake writer caps row groups at `batch_rows` (8,192) plus a byte cap, not at 131,072 or 65,536 rows. That cap is deliberate: it bounds writer memory (`src/storage.rs:428-453`).
- Basin compaction (target 128 MB) rewrites the files in any case. ARCHITECTURE §8.1 already says nothing may depend on physical sort order for the same reason.
- iceberg-rust 0.10.1 does not read `write.parquet.compression-*`; `spec/table_properties.rs` has no such constant.
- `write.metadata.delete-after-commit.enabled` is something the committing client acts on, and iceberg-rust does not implement it. It does not make "Basin's expiration" delete old metadata.
- The "sorted within a commit by `(url, retrieved_at)`" rule (l.263) is equally unenforced: the engine has no sort-order write path.

**Verified:** engine and iceberg code, yes. Basin's behavior, no.

**Fix:** rewrite the Table properties and Writer settings paragraphs as: "Format version 2, `gc.enabled` true. File, row-group and sort layout are whatever the engine writes and Basin compaction rewrites; no rule reads them. Old metadata files are removed by [the mechanism verified against Basin]." Drop l.263's sort clause.

### F8. Minor: a kept release cannot be rebuilt once Basin expires its pinned snapshots
**Where:** §8.1 l.823 and l.828; §8.3 l.839–841.

**Problem:**
- The inputs record names snapshot IDs, and Basin expires snapshots after 30 days.
- The receipt set appears only as a digest. A rerun therefore cannot recover which receipts the release included.
- So "a model run at a release's pinned inputs reproduces any grouping" holds only for 30 days.

**Fix:** rewrite §8.1 l.823 as "the input identity, the sorted receipt keys themselves (gzip), the provenance set, the generation digests and the run". Rewrite §8.3 so that the model reads `captures` filtered to that key list rather than at a snapshot.

### F9. Minor: the completion-row rules contradict the `meeting_records` table and leave MODS appearances without a completion marker
**Where:** §6 l.210–214 against §6.5 l.358–375; §6.7 l.387.

**Problem:**
- §6 says every non-PK column is nullable. But `congress`, `title`, `meeting_date`, `meeting_type`, `sittings`, `committees` and `is_completion` are not marked nullable, and `is_completion` must never be null.
- The MODS parser writes `appearance_records` with no `meeting_records` row beside it. A MODS record that lists no witnesses therefore leaves its body on the work list forever, unless its `readings` row is the marker.

**Fix:**
- Mark those columns nullable in the §6.5 table.
- Rewrite §6 l.212 as "…every non-PK column except `is_completion` null".
- Rewrite l.214 as "…`appearance_records` needs none: its producers' work lists are their parsers' `readings` rows, written in the same commit".

### F10. Minor: PK uniqueness is declared but never enforced
**Where:** §6 l.203; invariant 1 l.897.

**Problem:** Iceberg identifier fields are metadata only, and an append does not dedupe. A duplicate row from a producer bug would silently double links and counts. A maintained lake would then differ from a clean rebuild (invariant 4), with no change in the input identity.

**Fix:** rewrite §7.1 l.416 as "Publish MUST refuse when a pinned version's work list is not empty, or any lake PK is duplicated, at the pinned snapshot". This costs one O(n) aggregate per table.

### F11. Minor: one input that can never be read blocks every publish
**Where:** §7.1 l.416 with §6.2 l.276.

**Problem:** an operational failure writes no row, so the work list never empties. A body that always fails on the smallest runner, for example by running out of memory, stops all publishing.

**Fix:** rewrite §6.2 l.276 as "…`size_limit` when the input exceeds the parser's byte limit, which the parser version covers; an operational failure writes no row and is retried, and an input that fails at three daily runs is reported and listed in an `unreadable` registry, which removes it from the work list".

### F12. Minor: a stray code fence turns §7.11's bullets, all of §8 and §9's diagram into one code block
**Where:** l.784.

**Problem:**
- l.784 opens a fence.
- l.849's ```` ```mermaid ```` cannot close it, because a closing fence cannot carry an info string.
- l.879 closes it.

The §8 headings, and the TOC links that point to them, do not render.

**Evidence:** `/usr/bin/grep -n '^```'` lists 460, 480, 498, 544, 584, 642, 659, 689, 751, 782, **784**, 849, 879.

**Fix:** delete l.784–785.

### F13. Nit: `document_id`'s JSON shape is ambiguous
**Where:** §7.5 l.633–635.

**Problem:** "the compact JSON array ["bodies", sorted distinct logical body keys]" can be read as flat or nested. The engine nests it (`["bodies",[…]]`).

**Fix:** rewrite as "`["bodies",[k1,k2,…]]`, keys sorted bytewise".

### F14. Nit: dictionary encoding on unique-key columns
**Where:** §8.1 l.816–819.

**Problem:** `members.bioguide_id`, `bills.bill_id`, `nominations.nomination_id` and `committees.system_code` hold one distinct value per row. A dictionary adds a page and indirection for no gain. parquet-rs also falls back to plain encoding after a 1 MiB dictionary page, which gives mixed encodings.

**Fix:** type these key columns `string` in their own files.

### F15. Nit: a float comparison in `listing_signs`
**Where:** §7.3 l.530–531.

**Problem:** "≥ share × text_bytes" compares against a float.

**Fix:** make the registry hold an integer percent and compare `100 × link_text_bytes ≥ pct × text_bytes`.

### F16. Nit: parser versions are kept forever
**Where:** §6 l.216.

**Problem:** `readings` and `filename_readings` keep every parser version produced. Growth is unbounded, at about 100 MB per HTML or XML version, and the only operations allowed are append, create and drop.

**Fix:** rewrite as "…keep the versions any kept release's profile names; the next table-version rebuild (§6) omits the rest".

## 3. Checked and sound

- **Compact JSON is canonical.** Python's `json.dumps(ensure_ascii=False, separators, allow_nan=False)` and serde_json both escape with lowercase `\u00xx`, using `b"0123456789abcdef"` (serde_json `ser.rs:1721`). Neither escapes `/`, DEL or non-ASCII characters.
- **Truncated-hash collisions are negligible.** I found no collision among the 8-byte prefixes of 621,695 distinct body SHA-256s (2026-10-02 snapshot, `r8s_measure.py`). Analytically the probability is about 3×10⁻⁸ at 1.05M keys; `witness_key` is far smaller. The refusal at §8.2 l.835 covers the residue.
- **Identifier fields are legal.** Every PK column is non-null. iceberg 0.10.1 rejects optional identifier fields (`spec/schema/mod.rs:244-248`). Commits assert table UUID and ref snapshot (`transaction/append.rs:540-543`), as ARCHITECTURE §8.1 requires.
- **Export sort keys are unique**: `list` ends in `document_id`, and the others are `(list_row, ordinal)`, `(chamber, event_id)`, `system_code`, `bioguide_id`, `requested_url` and `(system_code, rank, bioguide_id)`. The last is unique on all 2,973 current roster rows, including 450 with a null rank.
- **Spicy-regs columns are all present.** Every column §6.4 names exists in the current `publication.v2.json` generation (`r8s_ref.py`), under prefixes of the stated form. `yea` and `nay` are BIGINT, which fits `int16`. `term_district` and `rank` are VARCHAR but all numeric today.
- **Release sizes match the estimates:**

  | File | Measured | Spec estimate |
  |---|---|---|
  | `links.parquet` (lookup profile, 621,695 keys) | 6.7 MB | 7–9 MB |
  | `url_state`-shaped file (966k rows) | 5.3 MB | 10 MB |
  | `filename` column, sorted, `DELTA_BYTE_ARRAY` (322k distinct names) | 1.49 MB (plain: 1.92 MB) | — |

  The `filename` measurement supports the encoding choice.
- **The browser reader supports the format.** hyparquet 1.31.2, the site's reader, decodes V2 pages with `DELTA_BYTE_ARRAY` (`datapage.js:195`) and plans reads by row range from the offset index (`plan.js:143`).
- **Casts work.** arrow-cast 58.4 casts Binary to FixedSizeBinary (`cast/mod.rs:241`), so `sha256()` output can become `fsb(32)`.
- **Timestamps are uniform.** `retrieved_at` comes in two shapes, both RFC 3339 with an offset or `Z`, with microseconds.
- **Scaling: no step is superlinear in its input.** Each join is a hash equi-join or anti-join on keys, and each grouping is linear. The largest in-memory items:
  - links unnest: about 4.2M rows, roughly 1 GB decoded with text;
  - placeholder distinct count: 718k distinct (body, context) pairs today;
  - archive fan-out: bounded at about 696k pairs (ARCHITECTURE §16);
  - connected components: the engine builds a union-find keyed by `String` with `HashMap<(String, String), usize>` (`topology.rs:86-132`), not the "dense integer IDs, 32 MB" of ARCHITECTURE §13.4. At about 4M tokens of about 64 bytes each, I estimate 1–2 GB. That fits a 7 GB runner but is about 50 times the stated figure.

## 4. Could not check

- **Byte-identity across thread counts and batch sizes.** I did not run the engine (forbidden against live services, and `scripts/check` does not exercise this path). F2 is inferred from code.
- **Basin (R2 Data Catalog) behavior**: whether compaction honors the compression properties, sorts, or deletes old metadata. This needs live catalog access.
- **Sizes I could not measure:**
  - `detail.parquet` and `list.parquet` in full: no model output exists, and the doc defers `detail` to F0;
  - phone heap and Range-request counts per detail view (about one request per leaf, with R2 serving one range per request).
- **Counts dated 2026-10-19.** My local snapshot is from 2026-10-02 (3.07M capture rows against the stated 3.9M).
- **Parser determinism and receipt shapes.** I did not open the receipts.
- **Effect of Unicode-version drift** on `name_key` and fingerprints, beyond noting that parser versions hash their locked dependencies.
