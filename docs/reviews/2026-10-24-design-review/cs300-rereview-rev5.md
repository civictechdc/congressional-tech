# CS 300 re-review: engine-first architecture revision 5 and simplification plan revision 3

Reviewer role: systems / data-intensive software engineering. Date: 2026-10-24.
Reviewed at `69080fac`: `docs/engine-first-architecture.md` revision 5 (cited **D5:line**) and
`docs/plans/simplification-plan-20261024.md` revision 3 (cited **P3:line**), plus my two earlier
reviews. Not read: pipeline code, engine source, tickets, the other reviews.

Measurements this pass (same Oct 19 snapshot, project venv, scripts `measurements/cs300_*.py`
beside this review; numbers quoted inline): the revision-5 numeric claims, the release files
in their revision-5 shapes, the lake folds, the fetch and recovery-import receipt line
shapes (one Oct 4 and one Oct 15 receipt fetched publicly with `congressional-tech-review/1.0`),
and hyparquet 1.31.2's `src/plan.js`.

**Correction to my rev-4 review first.** The owner is right: hyparquet 1.31.2 plans page
reads through the offset index (`useOffsetIndex`, `readOffsetIndex`, `pageLocations`,
`coalesceOverlappingPageRanges` in `src/plan.js`). My rev-4 §2(b) premise that reads are
row-group-granular was wrong, and the folded `detail` I measured as the page-granular winner
is the right layout. Revision 5's numbers for it hold (below).

## 1. Were the rev-4 findings resolved correctly?

| Finding | Status | Where | Verdict |
|---|---|---|---|
| F6 point reads | **Resolved** | D5:343, D5:370–375, D5:386–391, D5:569; P3:144–149, P3:246 | Offset index per file, folded `detail`, index fetched once per session. Measured fold of today's wide catalog (1,241,157 rows, 16.2 field/value pairs per row): 16 KB pages / 256-row batches → **81.2 MB, 3 leaf columns, ≈11 KB per view**; 64 KB pages → 73.6 MB, ≈43 KB per view. D5:372's "20–30 KB" is conservative. One cost is understated: the page indexes at 16 KB/256 rows are **868 KB** (234 KB at 64 KB pages), fetched once per session; D5:378–381 expects sharding "at roughly 10 times today's rows", but a sub-second first fetch on a phone wants ≤ 250 KB today. Either write 64 KB pages (43 KB/view, 234 KB index) or shard `detail` now. |
| F10 receipt listing | **Resolved** | D5:137–138, D5:181–185; P3:265–268 | Date-shaped prefixes only; the 49 non-date files (2.2M rows, counts match mine) read once by the backfill. |
| 412 path | **Resolved** | D5:111–114, D5:150–154; P3:183 | `unchanged`, no HEAD, no comparison; the weekly join uses the creating line. The "over half" figure matches (1,935 of 3,553 on Oct 16). |
| Early skip | **Resolved** | D5:411–421 | Identity from content high-water marks (receipt-key digest, row counts per parser version and catalog version, provenance digest, versions), so a review decision or SQL change publishes. Correct and metadata-only. |
| Manifest identity | **Resolved** | D5:422–432 | Content-only manifest, inputs in `inputs/<input_digest>.json`, several per release. Correct. |
| `url_state` in the release | **Resolved** | D5:346, D5:433–437 | Listed and decoded by the canary. Measured 42.8 MB with a 32-byte `last_sha` (32.3 MB of it); see §2 item 9. |
| Untyped bodies | **Resolved** | D5:205–209; P3:276–279 | Out of readings scope; every body gets a sniffed format, by receipt or by one ranged read. The sniff is a one-time pass of ≈1M small GETs (Class B, ≈$0.37, a few hours) that the plan does not cost; see §2 item 11. |
| Track C split | **Resolved** | P3:239–250 | Seven capabilities with estimates summing to the 3.5–5.5 weeks at P3:134. |
| Conflict retry (new in rev 5) | **Resolved, one refinement** | D5:168–173 | Recompute the work list, never re-send files: correct for idempotence. But "writes only what is still missing" discards the losing attempt's parsed rows, so a readings batch that loses a race to compaction re-parses bodies. Filter the already-parsed rows by the new work list instead of re-parsing; same correctness, no repeated I/O. |

## 2. New errors, inefficiencies and contradictions

Ranked by effect. Items 1–3 change counts or cost classes; the rest are sentences.

1. **The real-file rule removes most of today's "documents", and every size and count in
   §6.2 still assumes 1.24M rows (High).** D5:275–295 admits only PDF, ZIP, XML and
   page-shaped HTML as document files. Measured on today's documents by primary body:
   **453,751 caption segments** (`text/vtt`, 36.6 %), **98,205 XML metadata records**
   (MODS, PREMIS, meeting and witness XML), 9,945 playlists, 1,112 API JSON, and 101,067
   untyped bodies awaiting the sniff. Under the rule those are not documents, so the
   explorer lists roughly 0.5M documents, not 1.24M — unless they stay as fileless rows, which
   D5:366 ("a document with no saved file uses a prefix of its document_id") permits and
   D5:348–349 does not forbid. The design must say which. Consequences either way: the
   "about 1.26M documents" at D5:321–322 reuses my rev-4 count, which applied only the
   error-role and HTML exclusions, not the real-file rule; `list` ≈ 1.7 MB and `detail`
   ≈ 35 MB if captions and records leave, or 560k useless rows if they stay. Recommendation:
   a document needs at least one real file; caption segments, metadata records and
   playlists feed `url_state` and occurrences only; add `record_role` to the rule. See the
   data model, gap 2.
2. **"One URL, several complete files" is off by three orders of magnitude unless the key
   includes the archive member path (High).** D5:307–311 and D5:210–213 key fingerprint
   candidates by URL and say "today that is dozens of files"; P3:283 repeats "dozens
   today". Archive members are recorded at their container's URL: 694,683 attempts carry a
   member path (`original_path`), 300,316 bodies at 207,631 container URLs. Measured
   candidates with ≥ 2 distinct complete real non-HTML files: **by URL, 34,428 URLs,
   172,098 bodies, ≈545 GB** (277 GB PDF, 258 GB ZIP); **by endpoint `(URL, member path)`,
   148 endpoints, 297 bodies, 1.38 GB.** The text is right only with the endpoint key, and
   `captures` as specified (D5:176–180) has no member-path column. The grouping edge
   "shared canonical endpoint (filename plus URL)" (D5:272–273) survives only because member
   filenames differ; make the endpoint explicit everywhere.
3. **`captures` is not unique on `(receipt_key, receipt_line)` (High, correctness).**
   D5:176–177 states that key. A receipt line holds a `captures[]` list (the Oct 4 sample has
   3 entries on one line: the body, a prior 403 attempt's body, an embedded reference);
   measured: **3,909,134 rows over 2,596,054 distinct lines, up to 22,354 captures on one
   line** (a YouTube API batch), unique only with the capture pointer. "A retried append
   cannot duplicate" (D5:183) and the rebuild check (D5:186) need the real key:
   `(receipt_key, receipt_line, capture_index)`.
4. **The HTML link-shape rule is pattern-dependent and the pattern list is not written
   down (Medium).** D5:283–285 lists `.pdf, .zip, .doc, .docx, .xml, /download/, download=1,
   file_id=` "and similar". With exactly those, successful HTML bodies split 86,366 page-like
   (D5:290 says 86,343 ✓) and **16,775 file-like, not 44,047**; the 2,124 page-like bodies
   under 16 KB match. The rule decides which HTML bodies are documents and which connect
   nothing; the exact regex list belongs in the SQL (P3:294–297), not in prose.
5. **Deleting a failed candidate needs delete rights the publish job does not have
   (Medium).** D5:442–444: "a candidate that fails its canary is deleted". D5:533–535:
   publish holds release *write*; only maintenance holds release *delete*. Either publish
   gets delete on `releases/` or the weekly job deletes failed candidates (and the reader
   must then tolerate a third prefix for up to a week, which it does).
6. **"Two releases" is a floor, not a count (Low).** D5:442–446 keeps the live and last-good
   release but deletes "after the flip, the weekly job"; with daily publishes up to seven
   prefixes exist between weekly runs (≈1.4 GB, harmless). The 404-reload (D5:456–458,
   D5:553–555, P3:148–149) is the right safety net; say "at least two".
7. **Import-day dates: the design's 82,474 is not reproducible from the columns (Low).**
   Measured on documents' primary bodies: 756,452 have a real-fetch date on a day other than
   Sept 29 (D5:354 "about 756k" ✓), 368,748 have no `retrieved_at` (✓ exact), but **102,427**
   have `retrieved_at` only on 2026-09-29 (the import's synthetic timestamp), not 82,474.
   Define "import day" by the import run's receipts (`source_file`/run id), not by a date.
   Note also that recovery-import lines carry `retrieved_at` equal to the recovered copy's
   original timestamp (2000–2026 on the Oct 15 run), so `mode = retained_import` rows must
   never feed capture-date labels.
8. **Sniff coverage is larger than "74k bodies" (Low).** 87,537 documents' primary bodies
   have no media type anywhere in `captures` and 13,530 more are not in `captures` at all;
   the one-time ranged sniff (D5:207–209) covers ≈100k document bodies, not 74k, plus
   whatever the rule needs for the other 900k. One pass, metadata-sized, fine; cost it.
9. **`url_state` ships 32 MB the capture job does not use (Low).** Measured 42.8 MB, of which
   `last_sha` (32-byte binary) is 32.3 MB. Capture needs URL, attempts, last outcome, status
   and next-attempt time; the 412 tells it whether a body is new. Drop the hash: ≈10 MB per
   release and per capture run.
10. **Document types omit DOC/DOCX (Low).** 251 Word bodies (194 DOCX, 57 DOC) are documents
    the rule drops silently; add them or say they are excluded.
11. **Uncosted one-time passes (Low).** The sniff (≈1M ranged GETs), the PDF copies
    (261,055 objects; D5:201 and P3:215–220 say 365 GB, but the copies are the *decompressed*
    403 GB, so ≈$72/year of storage, not $66), and the full re-hash baseline (0.70 TB once).
12. **Browser unpacking of large legacy ZIPs (Low).** D5:463–468 unpacks "other older gzip
    bodies" with `DecompressionStream`; 579 bodies exceed 100 MB and the largest is 1.19 GB.
    Label those as downloads or copy them like PDFs.

**Contradictions between the documents.** None of substance. Decisions 22 and 23 are
reflected in both (D5:199–204 and D5:442–446; P3:54–55, P3:276–284, P3:362–364). Two small
mismatches: P3:283 still says "dozens today" where the design's own URL key gives 34k (item
2); and P3:47 says 62 cut-off URLs where the snapshot shows 201 cut-off bodies on 207
attempts (D5:116–117 ✓) and 59 URLs whose every copy is cut off.

**Verified claims.** 201 cut-off bodies at exactly 64 MiB with `size_limit`/`request_failed`
and HTTP 200 (D5:116–117 ✓). The Oct 15 run: 5,587 lines in 56 files, all `mode:
retained_import` with synthetic HTTP 200, shown in the old index as plain `saved` fetches
(D5:132–136, P3:223–226 ✓). 39,853 documents with more than one body (D5:296 ✓ exact);
26,419 of them hold a 503/retry-later body and 4,978 an untyped 2xx body (D5:297–300 ✓).
Basin facts as given are consistent with D5:237–247.

## 3. Re-grades

| Axis | Rev 4 | Rev 5 | Δ | Why |
|---|---|---|---|---|
| 1 Asymptotics | A− 90 | **A− 91** | +1 | Nothing recurring grows with history. The one O(545 GB) trap (item 2) is a key definition, not a mechanism. |
| 2 I/O and network | B+ 87 | **A− 89** | +2 | Detail views are 11–43 KB; two releases; the 868 KB offset index and the 32 MB of unused `url_state` are the residue. |
| 3 Do-once | A− 90 | **A− 91** | +1 | 412 path costs nothing; conflict retry recomputes rather than re-sends (re-parse nit). |
| 4 Bytes | B+ 87 | **A− 89** | +2 | Fold measured at 74–81 MB for today's wide catalog; `links` 10.7 MB; but all §6.2 sizes assume a population the rule removes (item 1). |
| 5 Compute and memory | A 93 | **A 93** | 0 | Unchanged; the rule-based grouping is cheaper still. |
| 6 Simplicity | B+ 86 | **B+ 87** | +1 | Fewer parsers, Basin maintenance, two releases, no early launch. Against it: the product rules add several paragraphs of SQL that must be exact (items 1, 2, 4), and the document population is undefined. |
| 7 Plan | B+ 85 | **A− 88** | +3 | Week one now measures the wide data; per-capability estimates; F0 stays a fixture, removing the ID-churn risk; one-time jobs scheduled. Short of better: "dozens today" (item 2), the uncosted sniff, and no step that decides item 1 before E1. |

**Architecture: A− (90), from A− (89).** Every mechanism I questioned is now right or
correctly gated. It does not move further because three things the product decisions
introduced are unresolved in the text: what a document is when its only bodies are
captions or records, the endpoint key for fingerprints, and the real unique key of
`captures`.

**Plan: A− (88), from B+ (85).** Measurement-first, parallel tracks, estimates per
capability, and the early-launch risk removed. Add a week-one decision on the document
population (item 1) and the endpoint key (item 2), because E1 and every size estimate depend
on them.

## Appendix: measurements this pass

| Measurement | Result |
|---|---|
| hyparquet 1.31.2 `src/plan.js` | `useOffsetIndex`, `readOffsetIndex`, `pageLocations`, `coalesceOverlappingPageRanges` present |
| `list` with `first_captured` + date kind (1,241,157 rows) | 3.9 MB zstd-3 / 3.4 MB zstd-9; 3.7 MB without the date columns |
| Folded `detail`, 290 list columns + scalars, 16.2 pairs/row | 16 KB pages: 81.2 MB, 3 leaves, page indexes 868 KB, ≈11 KB/view; 64 KB pages: 73.6 MB, 234 KB, ≈43 KB/view |
| `links` (8-byte key → row), all 962,897 bodies in body sets | 10.7 MB |
| `url_state` with binary sha | 42.8 MB (`last_sha` 32.3 MB) |
| `readings` today folded (491,710 rows) | 16.5 MB (`body_sha` 15.5 MB) vs 53.8 MB in 721 files |
| `filename_readings` fold, 200k sample → 1.39M pairs | 8.1 pairs/row; ≈32 MB |
| Captures key | 3,909,134 rows; 2,596,054 distinct `(receipt_key, receipt_line)`; unique with pointer; max 22,354 per line |
| Archive members | 694,683 attempts with a member path; 300,316 bodies; 207,631 container URLs |
| Fingerprint candidates | by URL: 34,428 URLs / 172,098 bodies / 545 GB; by `(URL, member)`: 148 / 297 / 1.38 GB |
| Documents by primary body | caption 453,751; PDF 285,555; HTML 201,907; untyped 101,067; XML records 98,205; XML documents 54,261; ZIP 34,622; playlist 9,945 |
| Date classes (primary body) | real date 756,452; `retrieved_at` only on 2026-09-29: 102,427; none: 368,748 |
| HTML 2xx bodies, link shape with the four listed patterns | page-like 86,366; file-like 16,775; page-like < 16 KB 2,124; < 2 KB 1,255 |
| Cut-off | 201 bodies, 207 attempts; 59 URLs with only cut-off copies |
| Oct 15 recovery run | 5,587 lines, 56 files, all `retained_import`, HTTP 200, `retrieved_at` 2000–2026 |
