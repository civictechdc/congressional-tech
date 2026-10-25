# Iceberg/Parquet audit with the evolutionary-refactoring lens

## Scope and method

- **Reviewed:** commit `1455011a`:
  - `docs/engine-first-architecture.md` (A);
  - `docs/engine-first-data-model.md` (DM);
  - `docs/plans/simplification-plan-20261024.md`;
  - `docs/plans/bindings-20261025.md`.
- **Mode:** Audit, read-only. I read the documents as code that five review rounds have patched.
- **Evidence:**
  - the pinned Oct 19 snapshot, queried with DuckDB through `wt/ct-viewer-publish/.venv`;
  - read-only public GETs, with an anonymous User-Agent;
  - docspec-rs at `d9c6719` and iceberg-rust 0.10.1, read in place.
- **Not run:** no builds and no tests. This is a document audit.

## Verdict: 85/100, ready to build once one rule is fixed

**Must fix.** The new PDF `intact` rule excludes every PDF fetched after the switch, and it hides a full decompression of the older PDFs (W1).

**Should fix.** There is no stated way to add a column to a lake table, and the engine refuses one today (W2).

**Structure.** The rest is cleanup that makes the next change cheaper:
- trim the `captures` columns no rule reads;
- name three release writer profiles instead of restating per-file settings;
- hash the registries as one set, and ship the capture scope in the release.

| Area | Score |
|---|---|
| Correctness | 84 (W1) |
| Cost and Big O | 88 |
| Evolvability | 80 (W2, W3, W4) |
| Specification craft | 88 |

## My earlier items (all landed, verified)

| Item | Where |
|---|---|
| X1: the endpoint is `(context_url, member_path)` again; comparisons are null-safe; a path shared by several members matches each; `entry_index` is evidence, reached through `pointer` | DM:112, 173-174, 373-374 |
| X2: bindings §3.3 paths, all checked in docspec-rs | `storage.rs:132-141, 376-391`; `catalog.rs:1163, 1347-1356`; `engine/export.rs:658`; `export.rs:36-38`; `storage/remote/objects.rs:534-541`; `engine.rs:84-85`; `engine/connected_components.rs:23-36`; `connected_components/topology.rs:104-108` |
| X2: dense integer IDs; C8 adds direct dependencies | A §9.3, A §13 |
| X3: page fingerprints come from the page parsers; the candidates stay narrow (owner decision) | DM:227-229 |
| X4: the `text_head` size, and readings reduced to narrow columns before joins | DM:230 |
| X5: maintenance is enabled on each new `captures` table, and the weekly job drops the old one | A:347; plan D6 (line 229) |

The bindings also correct one claim of mine. The `gc.enabled` reset at `catalog.rs:1163` sits inside `replace_baseline_snapshot`, so it runs only in lifecycle baseline compaction, not on every commit.

## Findings

### W1. `intact` excludes every new PDF and hides a 365 GB pass (must fix; reshape)

**What the specs say:**
- DM:215: `intact` comes "from `sniff`, for a PDF: true when `%%EOF` appears in its last 8 KB or a PDF reader opens it".
- DM:413: `real_files` requires `(format <> 'pdf' or r[sniff].intact)`.
- DM:226 and A:322: the sniff parser reads only bodies whose capture rows carry no sniff at the pinned version, with "one ranged read of its first bytes".

**What goes wrong:**
- **Every new PDF is excluded.** The fetcher records `sniffed_format` and `sniff_version` on every new capture, so the sniff parser never reads new bodies. They have no `r[sniff]` row, `intact` is null, and the predicate is null. Every PDF fetched after the switch fails `real_files`.
- **A hidden pass over every older PDF.** Older PDFs are stored as gzip, and the end of a gzip stream can only be reached by decompressing all of it. So `intact` for the 261,055 older PDFs is a full decompression of about 365 GB, not a ranged read. "A PDF reader opens it" is a full parse.
- **An unstated ordering.** D2 cannot finish before B13 without doing that pass itself.

**Fix:**
- The fetcher checks the tail of the spooled file it already holds (free) and records `intact` on the capture entry beside `sniffed_format`. `captures` carries it.
- The model takes it from the capture row when that row's sniff version is pinned, and from the sniff reading otherwise.
- For older gzip PDFs, B13 records `intact` in the verification record it already writes, because it decompresses every one anyway. Alternatively, sniff reads the last 8 KB of the `.pdf` copy with one suffix-range GET after B13.
- Drop "a PDF reader opens it" from sniff.

**Verify with:**
- an S fixture: a new PDF with a valid tail is a real file;
- an invariant: every PDF real file has a non-null `intact`.

### W2. No stated way to add a column to a lake table, and the engine refuses one (should fix; reshape)

**The pressure.** This round alone added four `readings` facts (`text_head`, `intact`, `meeting_refs`, `links.remove_date`) and seven `captures` columns. Further parser facts are the most likely next change.

**What the stack can do:**
- docspec-rs refuses any writer column the table lacks (`schema_mismatch`, `storage.rs:526-530`).
- iceberg-rust 0.10.1 can add optional columns, at the root or inside a list element's struct, as a metadata-only commit (`transaction/update_schema.rs:99-147`). The engine uses that only in a test (`engine/write/tests.rs:487`).
- So, as written, the first new fact a parser version needs means a new table or an engine change, and the specs name neither.

**Fix:**
- **DM §6.** State that `readings`, `filename_readings`, `committee_records` and `meeting_records` grow by adding optional columns. Older versions' rows read null, and the profile moves after the new version backfills.
- **`captures`.** It grows by a new ingest-mapping version (a rebuild), because history has to be re-read.
- **Engine.** Add to C2 (bindings §3.3): add the optional columns a job spec declares, before appending.
- **M1.** Add one add-column commit against Basin, including a field inside `links`' element struct, followed by a scan of the older files.

**Keep the versioned `captures` tables.** In an append-only lake, a mapping fix has to re-derive history. A rebuild reads 1.08 GB of receipts in minutes, and a drop reclaims the old table. The two mechanisms differ for a real reason: readings are per body, so a new version is a new partition; captures are per receipt, so a fix rewrites history.

### W3. `captures` holds columns no rule reads (delete)

**Measured.** I counted references to each `captures` column outside its own table in both specs. These are read by no rule, invariant or job:

| Column | Note |
|---|---|
| `pointer` | "Informative"; the ingest mapping uses it at ingest time only |
| `entry_index` | "Evidence, not identity" |
| `provider_status` | — |
| `publisher_requested` | Always false on import rows, so it equals `mode` |
| `h_content_type` | Equals `media_type` for a top-level body |
| `h_last_modified`, `h_etag`, `h_content_length` | — |

Two more columns are also unused:
- `observed_capture_ts` is carried into the `recoveries` relation (DM:553) but never written to `recoveries.parquet` (DM:602).
- `fidelity` and `transport` are read by nothing either.

I checked whether `fidelity` hides a correctness gap. The 363,742 `saved-text` bodies are Senate caption segments: all 6 sampled start with `WEBVTT`, so they sniff as captions and are excluded.

**Cost.**
- It isn't bytes: null-heavy columns compress to almost nothing.
- Every column must be mapped from every older receipt shape, with a test sample.
- Every mapping fix forces a `captures` rebuild.
- The ingest mapping is exactly where the next receipt shape lands.

**Fix:** one rule in DM §6.1: "`captures` holds a receipt field only when a rule, an invariant or a job reads it; the receipt keeps the rest." Then delete the eight columns, and either drop `observed_capture_ts` from §7.8 or write it out.

### W4. Release writer settings: per-file exceptions and three homes for one estimate (reshape)

**Seven files, three read patterns.** DM §8.1 gives seven files their own settings, but they follow only three read patterns:
- **whole:** `list`, `meetings`, `url_state`;
- **ranged:** `detail`, `occurrences`, `recoveries`;
- **lookup:** `links`.

**The drift is already visible.** `recoveries.parquet` was added in round W7 and needed a separate owner decision this round to get the 64 KB pages the other ranged files already had.

**Fix:** name three writer profiles in the shared settings.

| Profile | Settings |
|---|---|
| `whole` | defaults plus per-column encodings |
| `ranged` | 65,536-row groups; an offset index, 64 KB data pages and a 1,024-row page limit on every leaf; 1,024-row write batches |
| `lookup` | column and offset index on the key; 16 KB pages; one row group |

Each file names its profile and only its own encodings. C3's job spec takes the profile name, so the next ranged file costs one word.

**One estimate in three places.**
- "About 19 page reads, 50–90 KB" appears in DM:599 and A:565, and "about 19" in A §10.1.
- Two of those had to be edited in step last round.
- Keep the figure in DM §8.1 only.

### W5. Registries and the model profile (keep the profile; reshape the registries)

**Keep the model profile.** It is the one place versions are pinned, and it feeds both the completeness gate and the input identity.

**Hash the registries as one set (low).**
- There are 22 registries (DM:317-340), and the profile pins one version per registry.
- Any registry change is a profile change anyway, so hash the 19 model registries as one set and pin a single digest. Per-entry samples stay.
- That removes 18 entries from every profile and from the input identity, and nothing reads a single registry's version on its own.

**Ship the capture scope in the release (medium-low).**
- DM:315 says "Fetchers use the capture-scope version of the live release's profile". So the capture job has to fetch a registry file by its digest from the repository.
- Capture already reads `url_state` from the live release. Publish `capture_scope` beside it as a small release file. Capture then depends only on the release, and the queue and the fetcher can never disagree on scope.

### W6. Two sources for recovery fields (minor)

- `recovered_url` and `evidence_sha256` live both on `captures` import rows (DM:189) and in provenance `recoveries` (DM:142). §7.8 (DM:553-556) doesn't say which wins when they differ.
- **Fix:** take them from the import row. The decision supplies only `kind` (when the import has none), `identity_note` and `recovered_filename`.

### W7. Naming (minor)

- **`meeting_refs`** names two different things: the meetings a source record names (`readings`, DM:216) and a document's meetings (DM:509-517, `detail`). Rename the readings column, for example `named_meetings`.
- **The recovery category** is called `recovery_category` in `captures` (DM:189) but `prior_access_category` in the rule that reads it (DM:558). Use one name.

## Keep, as written

- **`readings` as one table partitioned by `(parser, parser_version)`.** Nulls for other parsers' columns are free in Parquet, and the partitions keep scans pruned. W1 moves `intact` to the capture row, where the fetcher already has the bytes.
- **Narrow fingerprint candidates** (owner decision). Edition bodies use candidate fingerprints only, so the result is deterministic.
- **Lake table properties and the bounded retry; the endpoint and null-safe joins; per-context link resolution** (about 5.5M targets, linear).

## What the next likely change costs

| Change | Cost today | After the fixes |
|---|---|---|
| New receipt shape | One case in the ingest mapping, plus a sample; a new mapping version and a `captures` rebuild (minutes) | Same, but fewer columns to map (W3) |
| New `readings` fact | Blocked: the engine refuses the column | A metadata-only add-column commit, then the new parser version backfills; older rows read null (W2) |
| New parser version | A background re-read (HTML/XML about 5 GB); about 200 MB per version kept (`text_head` plus links); publish waits behind the gate | Same |
| New release column | Fold: no schema change. Typed: a `schema_version` bump, deployed reader-first (A §11.4) | Same; a new ranged file names its profile (W4) |

## Residual risk

The two Basin behaviors M1 tests (expiration deleting files and DROP purging files) are still undocumented by Cloudflare. W2's add-column commit should join them in M1.
