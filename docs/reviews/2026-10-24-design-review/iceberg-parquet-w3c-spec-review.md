# Iceberg/Parquet review of the W3C-style specs

## Scope and method

- **Reviewed:** commit `39ae52d2`:
  - `docs/engine-first-architecture.md` (Architecture, Editor's Draft);
  - `docs/engine-first-data-model.md` (Data Model, Editor's Draft);
  - `docs/plans/simplification-plan-20261024.md` (Implementation Plan, Note).
- **Lens:** Iceberg, Parquet and query plans, plus a check that every owner decision survived the rewrite.
- **Not repeated:** findings already in `cs300-spec-review.md`.
- **Evidence:**
  - the pinned Oct 19 snapshot, queried with DuckDB through `wt/ct-viewer-publish/.venv`;
  - read-only GETs of public receipts and bodies;
  - pinned crate sources: iceberg 0.10.1, docspec-rs `d9c6719`, hyparquet 1.31.2.
- **Scripts:** in the session scratchpad: `links_probe*.py`, `xpath_probe.py`, `linkctx.py` and `pagelinks_size.py`.

## Verdict

The rewrite is clean, and nothing the owner decided was lost. All 46 of my earlier decisions trace to a section:
- links point at a file;
- PDF first;
- `url_key`;
- committee and meeting records;
- the typed `detail` core;
- keep-2 retention;
- Iceberg types;
- `xml_root`;
- the parsed `Last-Modified`;
- `fsb(8)` link keys;
- `DELTA_BYTE_ARRAY` filenames in V2 pages.

Every must-fix and should-fix from the CS300 spec review has landed.

Three things still need fixing before building. All were measured.

1. **Link context would be empty for almost all history.** The specs fill `page_links` from receipts' `links[]`, but older receipts rarely carry links. The fix is the one the owner suggested: re-derive links from the stored HTML and XML pages. The old pipeline already does this.
2. **The publisher's format groups can't be computed.** The recorded link paths have no usable ancestor, so the "listed together on the page" rule has nothing to work with.
3. **Re-fetched older files would be stored twice.** New writers check for a body only at `<sha>`, but every older body lives at `<sha>.gz`.

Three medium findings concern:
- engine table properties that may stop Basin's cleanup;
- a raw read of about 0.77 TB that the plan does twice;
- the list of discovered-but-unfetched URLs, which is lost at the switch.

## Findings

### W1. Link context comes from a field older receipts rarely have (major)

**What the specs say.** `page_links` is "filled from receipts' `links[]`" (DM §6.4, A §8.5, plan D1).

**What older receipts hold.** I sampled receipts in every family:
- The document-download receipts carry `record.links` on 6 of 100 lines and 20 of 1,000 lines.
- HTML download links have an empty `source_xpath`.
- Most link lists come from ZIP manifests and House meeting XML.

**Where the old link context comes from.** The old catalog's link labels (`source_link_label` on 519,668 source files) come from `read_document_sources` (`retention/index/records.py:401-560`). It re-parses retained raw bodies:
- Senate committee pages;
- House meeting XML;
- download pages;
- scraper records inside receipts.

**Consequences.** As written, history loses:
- "where each copy was seen" (decision 30);
- meeting references taken from a linking page (§9.5);
- publisher format groups (W2).

Parity (E4) would then report a large unexplained drop in link labels.

**Fix (the owner's suggestion, measured).** Links are a pure function of a page's bytes and the parser version, so the HTML and XML parsers emit them in the pass they already make for `readings`.
- Scale: 287,765 HTML/XML bodies (23 GB uncompressed; about 5 GB stored).
- On an 80-body sample: mean 14.5 links per body, median 1. That gives about 4.2M rows, which matches the specs' 3–5M estimate.
- Grain: one row per link per distinct page body, not per fetch, so a page fetched ten times stores its links once.
- The parent URL and fetch time come from `captures` joined on the page's SHA-256.

**Recommended shape:** a typed `links` column on the HTML/XML `readings` row:
- the column type is `list<struct<child_url, text, tag, basis, group_path, doc_type, add_date, publish_date>>`;
- it is native, not a fold, so the model may join on it;
- the real-file rule projects only the narrow columns, so an unread list column costs nothing.

**What this deletes:**
- the sixth lake table and its separate commit;
- its work list and its completion rows;
- its receipt-key digest in the input identity;
- its rebuild check;
- the "if it lags `captures`" case;
- `url_state.links_scanned`;
- `links[]` in new receipt lines (derivable, so principle 7 drops it);
- capture's replay mode, which re-reads retained bodies whenever `links_scanned` is false (`acquisition/raw_sync.py:298`).

**What changes:**
- §8.3's `linked_from` order becomes `(parent's first fetch nulls last, parent_url, parent_sha, link_index)`.
- The rebuild check becomes: "links re-derived from the bodies equal the stored rows".
- **Alternative:** a separate body-grain `page_links` table, keyed `(parent_sha, parser_version, link_index)`. It gives the same coverage but keeps a second work list and a second commit.

**Parity note.** Some old labels came from scraper JSON records inside receipts (`senate.json.gz`, `house-sites.json.gz`), not from bodies. E4 should report label coverage as its own cause. Any label that exists only there falls under the plan's §9 open issue.

### W2. The publisher-grouping rule can't be computed from the recorded paths (major)

**The rule.** DM §7.4 (a) groups files whose `source_xpath` shares "the nearest `<li>` or `<document>` ancestor", computed in SQL.

**The recorded paths can't support it.** Measured:
- HTML download links: the `source_xpath` is empty.
- govinfo METS links: the path is positional with no element names, such as `/*/*[4]/*[1]/*/*[2]`.
- House meeting XML links: the path is `/committee-meeting/meeting-documents/meeting-document/files/file`, with no position index. Every file in a meeting has the same string.

**Consequences.** Rule (a) either finds nothing, or it puts a whole meeting in one group. The "one file per format" guard then drops that group, so no edge is drawn. Only the same-folder, same-stem fallback (b) would work. The 16,156 groups were measured with (b); rule (a) has never been measured.

**Fix.** The link parser has the parsed page in hand, so it emits `group_path`: the indexed path of the nearest grouping ancestor (`li`, `tr`, `meeting-document`, `document`), or null. The SQL then groups on `(parent_sha, group_path)`. Add rule (a) to S's labeled sample.

### W3. Re-fetched older bodies are stored a second time, and the physical key is never recorded (major)

**The duplicate store.**
- A writer checks existence with a create-only PUT to `bodies/sha256/<aa>/<sha>` and its 412 (A §7.1, plan B5).
- Every older body sits at `<sha>.gz`, so re-fetching an older file does not get a 412. It stores a second copy at `<sha>`.

**How often this happens, measured:**
- 208,369 bodies (278 GB) were fetched on two or more different days;
- a normal day re-fetches up to 1,925 already-stored bodies (7.6 GB);
- a bulk day re-fetched 42,676 bodies (26.7 GB).

Over a recheck cycle, this duplicates most of the 0.70 TB under the lock, which is roughly $126 a year, forever. It breaks principle 3, "stored once".

**The physical key.** `captures` has no key or suffix column ("no `body_key`, derivable"), yet `saved_suffix` must name the physical key. Two cases have no rule:
- after this duplication, the same SHA-256 exists under two keys;
- after a crash, a new body sits at `<sha>` with only an `unchanged` line.

**Fix:**
- Before the create-only PUT, check whether the older copy exists (options below).
- Every `captures[]` entry records `stored_suffix` (`''` or `.gz`), including on `unchanged` lines; the writer knows it from the 412 or the check.
- `captures` carries it as a column, so `saved_suffix` becomes a lookup.
- `.pdf` is `stored_suffix = '.gz'` plus `format = 'pdf'`, confirmed by B13's verification record (W5).

**Options for the check:**
- **(a)** one HEAD of `<sha>.gz` per body not already in the run's own set (about 1–4k a day, well inside R2's free tier);
- **(b)** a frozen list of older SHA-256s, published once (8 MB as 8-byte prefixes), that seeds the run's set;
- **(c)** accept the duplicates.

### W4. Engine table properties contradict the spec's maintenance (medium)

The docspec-rs `table_properties()` (`src/storage.rs:132-141`) sets three properties.

**`commit.retry.num-retries = 0`. Keep it, and name it in the spec.**
- iceberg-rust 0.10.1's `Transaction::commit` otherwise retries 4 times by default (`transaction/mod.rs:175-230`).
- Each retry refreshes the table and re-applies the same `fast_append` with the same data files. That is exactly the re-send A §8.1 forbids.
- The engine's own loop then recomputes the work list.
- It MAY re-send the same files when the recomputed work list is unchanged (the competing commit was Basin compaction). That leaves no orphans.

**`gc.enabled = false`, and the commit path resets it on every commit (`src/catalog.rs:1163`).**
- It was set so the lifecycle store's own deletion actor owns file removal (`docs/reviews/retention-architecture-review.md` RA5, "KEEP native automatic cleanup disabled").
- The target has no lifecycle store, and Basin owns maintenance (A §8.8).
- Cloudflare's table-maintenance page doesn't say whether expiration honors `gc.enabled`. Iceberg's own engines refuse to delete files when it is false.
- If Basin honors it, expired snapshots never free their files, and compacted tables keep every superseded file.

**`write.metadata.delete-after-commit.enabled = false`.** Every `metadata.json` is kept forever. This is cheap, but there is no reason for it in the target.

**Fix:**
- DM §6 names the lake table properties:
  - `commit.retry.num-retries=0`;
  - `gc.enabled=true`;
  - `write.metadata.delete-after-commit.enabled=true`;
  - `write.parquet.compression-codec=zstd` with level 3;
  - `write.target-file-size-bytes`.
- Basin's compactor then writes with the same codec.
- M1 runs with exactly these properties and confirms that expiration deletes unreferenced data files.
- DM §6's writer settings (row groups, statistics) govern files the producer writes; compacted files are Basin's.

### W5. The plan reads the older PDFs twice and leaves the copies unverified (medium)

- **The copies.** B13 writes 261,055 `.pdf` copies (403 GB) that have no creating receipt line.
- **The weekly check.** A §7.1, B9 and DM invariant 2 make it re-hash once every body with no creating line. So the copies would be downloaded again: an unplanned 403 GB read.
- **The overlap.** B10's one-time full re-hash reads all 1.04M older bodies (0.70 TB). B13 has already read and SHA-256-checked the 365 GB of gzip PDFs among them.

**Fix: do it once.**
- B13 writes a `provenance/verification` record for both the `.gz` source and the `.pdf` copy, giving key, size, ETag and verified SHA-256. It has computed all of them.
- B10 skips keys that have a record. Running B13 before B10, or merging them into one pass over older bodies, saves about 365 GB of reads.
- The weekly LIST join maps `.pdf` keys to their SHA-256 and suffix.
- With the copies, A §7.4's "about 1,000 list requests" becomes about 1,300.

### W6. The list of discovered-but-unfetched URLs is lost at the switch (medium)

- **Today.** The state holds 16,753 URLs with no body and zero attempts. They were discovered but never fetched.
- **Target.** `url_state` is "one row per requested URL" from `captures` (DM §7.6). A link found on a page but not fetched in that run has no row. It waits until its parent page is next rechecked.
- **Fix.** Derive the queue: `url_state` ∪ (child URLs from W1's links, in the capture-scope registry, with no capture row). Such a row has `attempts = 0` and `next_attempt_at = now`. Nothing new is stored. This also replaces `links_scanned` (W1).

### W7. A detail view is 24 page reads, not about 15 (low)

The typed core plus the fold has 24 Parquet leaf columns (counted with pyarrow from DM §8.1):
- `recoveries`: 8 leaves;
- `alternates`: 4;
- `meeting_refs`: 2;
- the fold: 2;
- everything else: 8.

Each leaf needs a page read even when the row's list is empty.

There is no per-view byte budget (decision 35), so this only needs the A §10.1 figures corrected, measured in F0.

**Optional:** `recoveries` exists on about 24k of about 0.65M documents. It could become a ranged side file, like `occurrences`, with `rec_start` and `rec_len` in `detail`. That removes 8 of the 24 reads from almost every view.

### W8. Minor

1. **The `links` point lookup** needs hyparquet's `usePageIndex: true`, which defaults to false (`types.d.ts:48`). Only then does it read the column index and skip pages. A §11.1 and plan A1 name only `useOffsetIndex`.
2. **`detail.link_key` is undefined** for documents with several real bodies, and for recovery-only ones. Recovery bodies must not be keys. Proposed rule: the saved body's prefix, else the recovery's URL key.
3. **`url_key`'s "repeat until nothing changes" has no bound.** Plain SQL can't loop, so it needs a recursive CTE. State a fixed depth (2), and report URLs that are still wrapped.
4. **M2 should include `url_key` and the link join** (about 4.2M + 1.7M URLs), as well as the joins it already lists.
5. **The 2.2 MB `list` estimate is stale.** It predates `committee_name`, `meeting_keys`, the two dates, `date_kind`, `saved_kind` and `hidden`. Re-measure in F0.
6. **`filename_readings.source_url` is nullable**, so that PK can't be declared as Iceberg identifier fields (DM §6 says "MAY"). Either store `''`, or don't declare it.
7. **The plan's header says "Editor's Draft",** but its status and every reference call it a Note.

## Decisions preserved

These were spot-checked against owner decisions 10–61:
- **Pages and links:** document pages only; 16-hex link keys that point at a file; the refusal on a key collision.
- **Devices:** mid-range phones, with a heap budget only.
- **Older copies:** `.pdf` copies of older PDFs, plus `DecompressionStream` in the browser.
- **What counts as a file:** real files only; same-text merges; any content format; listing pages excluded.
- **Dates and recoveries:** capture-date labels; the import-run registry; recoveries labeled by kind with an attachment rule.
- **Links:** `url_key` with wrappers and page state; renditions with PDF first and one file per format.
- **Meetings and committees:** meeting and committee records from raw, with total-order tie-breaks; `meeting_keys` as `chamber:event_id`; `document_date` with its source; official record keys; committee names.
- **Reviews and retention:** review hide and merge; keep-2 retention; no schedule.
- **Parked:** VARIANT, with the right three conditions.
- **Origin:** the allowlist is deleted.

## Still with the owner

**The bucket lock (plan B1).** It is still pending, and it gates B13, the plan's largest raw write.

## Owner decisions (2026-10-24)

### W1: links live on the page's reading

- **The design.**
  - The HTML and XML parsers write a typed `links` column on each `readings` row, in the same pass. That pass reads every saved page once per parser version.
  - Each link carries `child_url`, `text`, `tag`, `basis`, `group_path`, `doc_type`, `add_date` and `publish_date`.
  - The parent URL and fetch time come from `captures` on the page's SHA-256.
- **What users get.** "Where each copy was seen" works for all history, not just new captures.
- **What goes:**
  - the `page_links` table, so there are 5 lake tables;
  - its work list, commit and completion rows;
  - its receipt-key digest in the input identity;
  - `url_state.links_scanned`;
  - `links[]` in new receipt lines;
  - capture's replay mode.
- **Where else it is used.** `linked_from`, meeting references from a linking page, and publisher format groups (W2's `group_path`) all read from it.

### W3: one quick existence check per file

- **The owner asked:** "Wouldn't they be deduped by the hashing?"
  - The hash is the same, but the object name differs: older files are named `<sha>.gz`, new ones `<sha>`.
  - The create-only write refuses only an exact name, so the hash alone doesn't catch the match.
- **The fix.** Before the create-only PUT, the writer makes one existence check on `<sha>.gz` for any body not already in the run's own set. This is about 1–4k checks a day.
- **The record.** Every capture entry records `stored_suffix` (`''` or `.gz`), including on `unchanged` lines. `captures` carries it, so `saved_suffix` is a lookup.
- **Older PDFs.** They still get their `.pdf` copies through B13, after the lock.

### W6: linked documents we never fetched are queued

- `url_state` also includes child URLs from page links that fall within the capture scope and have no capture row, with `attempts = 0` and due now. These rows are computed, not stored.
- Today's 16,753 waiting links therefore survive the switch.

### W7: recoveries move to their own ranged release file

- **The file:**
  - `recoveries.parquet` holds one row per recovery, in `(list_row, ordinal)` order, with the columns of today's `detail.recoveries` struct;
  - offset index on every column;
  - like `occurrences`, it is read only for the range a document names.
- **`detail`** replaces the 8 recovery leaves with `rec_start` and `rec_len` (int32). It goes from 24 leaves to 18, so a page without a recovery makes about 18 reads.
- **Invariants:**
  - the recovery ranges partition `recoveries.parquet` exactly;
  - a recovery-only document's range is non-empty.
- **The figures.** Correct A §10.1's detail-read figures, then measure in F0.
