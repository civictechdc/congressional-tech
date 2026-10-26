# Iceberg, Parquet and DataFusion review, round 7

**Reviewed:** A, DM, P and B at `40ee51b2`, read in full, plus `decisions.md`. My score and findings were written to `iceberg-review7-own.md` before I opened the lead's opinion. SF5 was found afterwards, while checking the lead's "Already checked" claim.

**Primary sources:**
- the pinned crates in the local Cargo registry: iceberg 0.10.1, iceberg-datafusion 0.10.1, DataFusion 53.1.0, arrow, arrow-json and parquet 58.4.0, opendal 0.57.0;
- docspec-rs at `d9c6719` (its `main`, unchanged);
- hyparquet 1.31.2 from the site's `node_modules`;
- Basin Catalog's docs, fetched 2026-10-26;
- all 2,289 files of the raw receipt mirror;
- 50 HEAD requests to the public origin.

Scripts are `ice7_*.py` in this folder; results are in `ice7_out/`.

**Tags:** *(measured)* = measured in this round; *(docs)* = from A, DM, P or B; *(est.)* = estimate.

## Score

| Area | Score |
|---|---|
| Lake design | 80 |
| Release files | 87 |
| Query plan | 83 |
| Engine fit | 74 |
| **Overall** | **81 / 100** |

Every review-6 finding landed, most as clean rewrites (status table below). The rest of the gap comes from raw data the documents had not yet been tested against:

- the older receipts the lake is built from;
- the ETags of older large bodies.

## Must-fix

### MF1. The named receipt reader refuses 37% of the raw lines

**Location:** A §13 item 1; B §3.2, "Captures ingest"; B §3.3 C1; P §5. B §3.2 says the reader is "measured before any receipt parser is written", but no step in P §5 runs that measurement.

**Failure.** Measured on all 2,289 receipts:

- **Every line is an older line.** All 2,596,054 lines keep their fetch fields under `record`, which has 11,618 distinct keys across the corpus. Some keys are data values, such as meeting IDs and Senate hostnames.
- **Type conflicts.**
  - `record` is a list, not an object, in 99 lines across 27 receipts.
  - `record.http_status` is `""` in 27 lines.
  - `captures[].pointer` mixes integers and strings in 1,151,047 entries.
- **Huge lines.** The longest line is 187,661,340 bytes.

DataFusion 53's JSON source calls `ReaderBuilder::new(schema).with_batch_size(batch_size)` and nothing else (`datafusion-datasource-json/src/source.rs:307-335`). `JsonOptions` exposes only compression, level, schema inference and line-delimiting (`datafusion-common/src/config.rs:3086-3113`). arrow-json therefore keeps `ignore_type_conflicts = false` and `coerce_primitive = false` (`arrow-json/src/reader/mod.rs:190-213`). A number read as a string, or a list read as a struct, is an error (`string_array.rs:78-80`, `struct_array.rs:150`). One conflicting value fails its whole receipt.

That refuses 27 of 2,289 receipts, holding 963,658 of 2,596,054 lines *(measured)*, among them the 778,684-line `documents/undated` file. arrow-json 58 already has both escape hatches (`with_coerce_primitive`, `with_ignore_type_conflicts`, `mod.rs:269-315`); DataFusion just does not pass them through.

**Fix (rewrites; P's text does not grow).**
- **B §3.3 C1**, last clause: "receipts through arrow-json with the ingest mapping's explicit schema, `with_coerce_primitive` and `with_ignore_type_conflicts` on, and the nulled conflicts counted per receipt (DataFusion's JSON source sets neither)".
- **A §13 item 1:** "… the JSON lines of receipts and provenance read with an explicit schema, a type conflict becoming a counted null; …".
- **P §5.2 inputs:** replace "captures `db033173…`" with "the 2,289 receipts through that reader and the draft ingest mapping".

## Should-fix

### SF1. The `captures` grain drops older lines' `file_references`

**Location:** DM §6.1, first sentence; DM §5.2.

**Failure.** 464,110 older lines reference 534,283 bodies through `file_references` *(measured)*. The entries carry `sha256`, `body_key`, `bytes` (as strings) and an absolute local `original_path`. DM §5.2 never names the field, and DM §6.1 counts rows only per `captures[]` entry. DM's own figure of 1,041,863 bodiless lines holds only if these count as bodies: 1,505,687 lines have an empty `captures[]` *(measured)*. Read literally, the rule loses about 14% of capture rows. D1's old-index comparison would catch it, but only after the ingest is built.

**Fix.** DM §6.1: "One row per body a line references, a `captures[]` entry or an older line's `file_references` entry, plus one row per line that references none." This replaces the current sentence and adds no length.

### SF2. "No dictionary page" contradicts the `dict` columns

**Location:** A §11.1; P §6.3 C3 contract test.

**Failure.** DM §8.1 keeps dictionaries on `dict` leaves. That is six of `detail`'s 19 leaves: `saved_suffix`, `saved_media_type`, `alternates.format`, `alternates.suffix`, `meeting_refs.chamber`, and the fold's `field`. hyparquet fetches a chunk's dictionary page whenever it has one (`hyparquet/src/rowgroup.js:93-129`). A §11.1's "with no dictionary page beneath it" is false. The C3 test "hyparquet page reads with no dictionary page under a ranged read" fails against the specified settings, or tempts an implementer to drop dictionaries DM requires.

**Fix.** Delete "with no dictionary page beneath it" from A §11.1, since DM §8.1 owns the rule. P C3: "hyparquet page reads in which only `dict` leaves bring a dictionary page."

### SF3. Named-step materialization has no binding

**Location:** B §3.3, C1, C6 and C7.

**Failure.** A §9.1 and §13 item 1 require a step "materialized once within the memory pool". In DataFusion 53, `DataFrame::cache()` collects into a `MemTable` that the pool does not account for, unless a `cache_factory` is installed (`datafusion/src/dataframe/mod.rs:2387-2402`). No B row names that work.

**Fix.** B §3.3 C1 work: add "named steps materialized once through a pool-accounted `cache_factory` (`DataFrame::cache` collects outside the pool)". This adds one clause to a Note.

### SF4. M1 has no decision rule and checks no content

**Location:** P §5.1, item 2 and "Decides".

**Failure.** M1 counts files, manifests and the bytes expiration removed, but never checks that Basin's compacted files read back the same rows through the engine. "Bounded" also has no threshold, although P §3 requires "the decision rule first". Basin's docs say compaction "combines new files that have not been compacted yet", so the outcome is genuinely open.

**Fix.** P M1.2: "… count the current snapshot's data files and manifests and the bytes expiration removed, and check the rows read back equal those appended." "Decides: Iceberg stays (after the tenth run, no more data files or manifests per partition than after the fifth, and the rows unchanged)". This grows the item by one clause.

### SF5. Invariant 2 and the raw check assume no older body was uploaded multipart

**Location:** DM §10, invariant 2; A §7.4, "Raw check".

**Failure.** I sent HEAD requests over `congressional-data.spicygov.ai` to a seeded random sample of older bodies *(measured)*:

| Older bodies sampled | Multipart ETags |
|---|---|
| 20 over 100 MiB | 6 (suffixes `-14` to `-26`, about 16 MiB parts) |
| 30 between 8 and 100 MiB | 0 |

For example, `bodies/sha256/29/29594f8d…4879d.gz` has ETag `"838dc2a5…bb64-24"`. 528 older bodies exceed 100 MiB *(measured)*, so about 160 *(est.)* would fail "no body ETag contains `-`". A §7.4's raw check compares "the size and MD5" against a verification record, but for these bodies the record's `etag` is not an MD5. No raw data is at risk; the test and the check would flag real bodies falsely.

**Fix.**
- Invariant 2: "… no body a new line created has an ETag containing `-` …".
- A §7.4: "… the size and ETag its creating line or verification record gives …".

## Minor

- **m1. DM §6 codec property.** "`write.parquet.compression-codec` zstd at level 3": Iceberg spells the level `write.parquet.compression-level`. Basin's docs do not say it honors either property, and the engine's writer sets the codec itself. Delete the clause.
- **m2. A §8.6.** "compaction moves a few GB a month" assumes files are compacted again toward 128 MB. That is the open question M1.2 measures. Delete the sentence.
- **m3. P §5.2.** "as one plan": grouping is not SQL, so no single DataFusion plan runs the whole model. Read it as "as inlined steps".
- **m4. Build side (B §3.3 C3).** The clause sits under export, but it belongs to C6. The cheapest implementation is a deletion: drop the provider's row counts (`ds/query.rs:365-369`). DataFusion then never swaps a scan, because it swaps only when both sides have statistics (`datafusion-physical-optimizer/src/join_selection.rs:75-81`). P C6's test then asserts the build sides from EXPLAIN, instead of only "M2's build sizes".
- **m5. Conflict retry (A §8.1).** When the work list is unchanged, which is the usual case after a maintenance commit, re-commit the files already written. Rewrite: "reusing the files already written when the work list is unchanged; otherwise the losing attempt's files become orphans."
- **m6. Basin's maintenance token (A §14).** Catalog-level maintenance needs "an API token as a service credential" with R2 write on the bucket (Basin docs), so expiration and purge run with bucket-wide write. Raw stays safe only through the lock, which A §14 already names. One clause would cover it, but that grows §14; optional.

**Claims that verified:**

- **Guarded commits.** A §8.1 matches iceberg-rust 0.10.1's rebase (`transaction/mod.rs:218-249`) and docspec-rs's guard (`ds/catalog.rs:1334-1352`).
- **CTEs and hash joins.**
  - DataFusion inlines CTEs (`datafusion-sql/src/cte.rs`, `non_recursive_cte`).
  - Hash-join builds `try_grow` and never spill (`joins/hash_join/exec.rs:1874`).
- **iceberg-datafusion 0.10.1.**
  - It converts Eq, InList and IsNull filters (`expr_to_predicate.rs`).
  - It prints `predicate:[…]` in EXPLAIN (`physical_plan/scan.rs:185-196`).
  - It scans a pinned snapshot (`table/mod.rs:279`).
- **Basin's dashboard.** It takes a snapshot age in minutes, so M1's short expiration is feasible.
- **hyparquet `links` lookups.** It compares binary bounds byte-wise (`filter.js:235-257`; `utils.js:53-64`), so lookups on `links` work.
- **B §3.3's new line references.** `ds/storage.rs:453`, `ds/engine/export.rs:508`, `pipeline.rs:688`, `ds/query.rs:369`, `ds/storage/schema.rs:101`, and `topology.rs:31-74` all hold.

## Review-6 status

| R6 finding | Status | Where |
|---|---|---|
| MF1, M1 blind to growth and expiration | RESOLVED; a decision rule and content check remain (SF4) | P §5.1 item 2 (l. 85), "Decides" (l. 88); A §8.6 has no fallback paragraph |
| MF2, dictionary pages under ranged reads | RESOLVED; the A §11.1 and P C3 contradiction is new (SF2) | DM §8.1 l. 638, 643, 650; DM §4 l. 84 |
| SF1, iceberg-rust rebase | RESOLVED | A §8.1 l. 278; A §13 item 2 l. 479; B C2 l. 88; DM §6 no longer cites `commit.retry` |
| SF2, nested schema growth | RESOLVED by owner decision (rebuild, never evolve) | DM §6 l. 179; A §8.6 l. 318; old M1.4 removed |
| SF3, one-plan shape | PARTLY: the specs are fixed; the binding (SF3) and M2's wording (m3) are not | A §9.1 l. 326; A §13 item 1 l. 478; P §5.2 l. 96 |
| SF4, build side | PARTLY: the rule landed; B places it under C3 and P C6 asserts no build sides (m4) | A §13 item 6 l. 483; B C3 l. 89; P C6 l. 224 |
| SF5, provider prunes nothing | RESOLVED | A §13 item 1 l. 478; B C1 l. 87; P §5.1 l. 85; P C1 l. 219 |
| SF6, Basin ignores table properties | RESOLVED; the codec-level wording remains (m1) | DM §6 l. 175; A §8.6 l. 314; P D6 l. 250 |
| MN1, `readings` sort clause | RESOLVED | DM §6.2 l. 248 |
| MN2, "only read and append" | RESOLVED | A §13 l. 489 |
| MN3, drop with purge | RESOLVED | A §8.6 l. 318; A §13 item 2 l. 479 |
| MN4, `list` size | RESOLVED | DM §8.1 l. 649; A §10.1 l. 373 |
| MN5, offset indexes with the footer | OPEN (not adopted; harmless) | A §11.1 l. 423 |
| MN6, race against a second client | RESOLVED | P §5.1 l. 84 |
| MN7, fallback paragraph in A | RESOLVED (moved to P) | P §5.1 l. 88 |
| MN8, opendal Content-MD5 | RESOLVED | B C5 l. 91 |

reconciliation-review-6.md agrees with this table. Rows 3.1–3.7 and 1.7 record the same dispositions.

## The lead's claims

| Claim | Verdict | Evidence |
|---|---|---|
| Grade about 87 | **DISAGREE** (81) | MF1 and SF1 come from measuring the raw receipts; SF2 and SF5 are contradictions with code or data. |
| Raw-data safety 9.5 | **AGREE** | Create-only writes, the lock, and B0's backup-first rewrite hold. The local paths in `file_references.original_path` fall inside B0's by-field scan. SF5 is a test defect, not a safety gap. |
| Grounded in data 9.5 | **PARTLY** (8.5) | The older receipt shapes behind `captures` are unmeasured in the documents: `record` has 11,618 keys, `file_references` is missing, and there are type conflicts. The 4.2M-link figure rests on an 80-body sample (DM §6.2). A §8.6's "few GB a month" contradicts Basin's docs. |
| Internal consistency 9 | **PARTLY** (8) | A §11.1 and P C3 contradict DM §8.1. DM §6.1's grain contradicts its own bodiless count. Invariant 2 fails on older bodies. "193 references, 0 problems" checks links, not meaning. |
| Executable plan 8.5; M1 and M2 are the two biggest bets | **PARTLY** (8) | Both are real. M1 now decides growth and expiration but needs SF4. M2 decides the step form; its memory verdict is provisional on scaled links, and D2 repeats it. The receipt reader is a third bet, unscheduled and already failing on data (MF1). |
| Simplicity 7 | **AGREE** | In my lens, deletions remain: the codec clause, the "few GB" sentence, and provider row counts in place of new build-side code. |
| Readability and concision 7 | **AGREE** | Verified: DM is 9,929 words and the four documents 27,835 *(measured)*. |
| Hold-back 1: grouping is the hard part, checked only on fixtures | **PARTLY** | True, but the first real-data failure in my lens is ingest, not grouping. Grouping's memory is M2's question. |
| Hold-back 2: ceremony | **PARTLY** | Mostly outside my lens. P §3's "project runners only" rule is load-bearing, not ceremony. |
| Hold-back 3: density | **AGREE** | The word counts match. |
| Nit: A §6 diagram omits bodiless rows | **AGREE** | A l. 183. The bigger miss is DM §6.1's grain (SF1). |
| Nit: P §1's `stored_sha256` | **AGREE** | P l. 29 against DM §6.1 ("no `stored_sha256`"). |
| Raise 1: run S1 as an executable model on real data | **AGREE** | Extend it to the ingest mapping over all receipts (MF1). |
| Raise 2: cut boilerplate; another concision pass on DM §7 | **PARTLY** | Outside my lens. My fixes delete or replace text, with one clause added each for SF3, SF4 and optional m6. |
| Raise 3: run M1 and M2, then re-grade | **AGREE** | After M1 gets its rule (SF4) and M2 reads receipts (MF1). |
| Already checked: no older body ETag contains `-` | **DISAGREE** | New evidence: 6 of 20 sampled older bodies over 100 MiB have multipart ETags (SF5). |

**What the lead missed:**

- the receipt reader (MF1);
- the `file_references` grain (SF1);
- the dictionary contradiction (SF2);
- the materialization binding (SF3);
- M1's missing rule and content check (SF4);
- multipart ETags on older bodies (SF5).
