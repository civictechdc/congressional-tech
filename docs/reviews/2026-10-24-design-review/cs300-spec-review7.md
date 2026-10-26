# Review 7: specification quality of A, DM, P and B at 40ee51b2

Read cold and in full. My independent pass is `spec-review7-own.md` (written before the lead's opinion or the reconciliation were opened); this file adds the review-6 status table, the verdicts on the lead's claims, and the data checks. One finding from the independent pass (S5) was softened after a further measurement, and the change is shown. Numbers are **[measured]** (scripts `spec7_*.py`, outputs `spec7_out_*.txt` in this folder), **[doc]** or **[est.]**.

## 1. Score: 85 / 100

| Area | Score |
|---|---|
| Correctness and completeness | 84 |
| Determinism and failure behavior | 86 |
| Data model | 85 |
| Specification craft | 84 |
| Plan and bindings | 86 |

The three review-6 must-fixes are closed and most should-fixes were folded into the rule they touched. What remains: one regression (three `list` columns lost their derivation), one contradiction between the reader's and the writer's contract (dictionary pages under ranged reads), two inputs still undefined (`context_url` of a top-level row; the PDF copier's candidates, whose miss is permanent under the new sniff rule), and two plan numbers the data disputes. A second team would build the same system except where S1 and S3 leave a guess. No must-fix.

## 2. Findings

### Must-fix

None.

### Should-fix

**S1. DM §7.5 "Columns" dropped the derivation of three `list` columns.** `list.parquet` (§8.1) carries `format`, `congress` and `document_family`; §7.5 derives `document_kind`, `committee_name` and the meeting and record keys only. The review-6 text's "the facets of the saved file's filename reading" was cut in the concision pass. *Rewrite the Columns line:* "**Columns:** the names derived above and, from the saved file, `format` and its filename reading's `congress` and `document_family`, typed as `detail` and `list` read them (§8.1), plus `document_id` fsb(32), …".

**S2. A §11.1 and DM §8.1 disagree on dictionary pages.** A §11.1 promises a detail view "with no dictionary page beneath it" and P C3's contract test asserts "no dictionary page under a ranged read"; DM §8.1 writes "dictionary encoding only on `dict` columns", and `detail`, `occurrences` and `recoveries`, all ranged, carry `dict` columns, whose data pages decode only with the column chunk's dictionary page, which the offset index does not list. *Fix by deletion:* drop "with no dictionary page beneath it" from A §11.1 and "with no dictionary page under a ranged read" from P C3; the reader fetches each row group's dictionary pages with its offset index, once per session.

**S3. `context_url` of a top-level row is undefined.** DM §5.2: "the URL the body is evidence for: the container's URL for an archive member" leaves requested versus final open for the common case, and endpoints, edition ambiguity and link contexts all key on it. *Rewrite the cell:* "The final `url`, or the container's `url` for an archive member: the URL the body is evidence for."

**S4. The PDF copier's candidate rule is unnamed, and a miss is now permanent.** P B13 and B §3.1 say "candidates from capture rows"; older rows carry no sniff, so the only signals are the server's media type (which DM §5.2 forbids for classification) and the locator. DM §6.2 then sets `intact = false` for an older gzip PDF with no verified copy, in a `sniff` row that is never recomputed (one row per body, parser and version), so the only repair is a new sniff version over 1.04M bodies. Measured against the old catalog's own sniff **[spec7_measure.py]**: a media-type rule selects 261,056 bodies (DM's 261,055), over-includes about 34,329 non-PDF bodies (harmless copies) and misses about 69 PDFs. *Rewrite DM §6.2's sentence:* "An older gzip PDF with no verified copy is read whole from its `.gz` and reported, so a copier miss costs one full read, not a new sniff version." *P B13:* "candidates: older bodies whose media type or locator says PDF; the sniff report names any it missed."

**S5. P D1's "47,359 of them carry one on their line" reads one time field.** The first number, 522,448 untimed rows in dated receipts, reproduces exactly **[spec7_measure2.py]**. A scan of the receipt mirror reading seven time fields finds `captured_at` on 452,186 lines (the dated Senate caption runs) and only 35,970 dated-prefix capture entries with no time field at all **[spec7_scan_receipts.py]**. Either `captured_at` is not a fetch time, in which case the mapping should say so, or D1's number is 10× low and DM §7.5's "about 30% of listed documents … no capture date" shrinks. *Fix:* name the time fields the ingest mapping reads in DM §6.1's older-lines bullet, and re-measure D1 from them.

### Minor

1. DM §7.3: `api_row` and the feed-root test read "the capture's URL"; `error_signs` reads `c.url`. Write `c.url` in all three.
2. B §3.1 PDF copier: "on a 412, compare the existing object's ETag with the expected MD5" needs a HEAD the body-store contract (A §7.1 step 3) forbids; let the raw check's LIST verify it against the recorded MD5.
3. DM §6.2: `format` is non-null on every reading row but only `sniff` finds it; say "the sniffed format, on every row".
4. DM §6.2 `links`: "every URL-valued string in a JSON body" — a string that parses as an absolute http(s) URL.
5. DM §6.2 `text_bytes`, `text_head`: say "of the whole page"; the near-empty test and the listing share read them while the fingerprint reads main content.
6. `locator` is defined in A §3 and again in DM §7.3.
7. P S1 fixture 2 omits the shared endpoint that makes "no document holds both editions" true (fixture 3 is the case without one).
8. P S2 "a recovery import for a URL never fetched → the URL enters the queue" holds only when a page links it.
9. DM §5.2 "full provider metadata" — say which provider fields a line may keep.
10. P §4 item 1 omits "the old writers patched" that the track-B row names.
11. P E4 "`document_id` keeps today's formula, but its inputs now include real web pages": on 10,000 single-body document-role catalog rows **[spec7_ids_format.py]**, today keys 37% by `["bodies", …]` and 62% by `["sources", …]`; the sources-keyed rows are 3,653 captions and 66 playlists (never listed), 1,128 HTML pages (E4's case), 584 untyped bodies, 77 XML and 12 PDFs. The formula's shape is confirmed; add "and untyped bodies" to the bullet. *(My independent pass called this a should-fix on the 62% figure; the format breakdown shows the reconciliation's reading holds for listed formats, so it is a wording nit.)*
12. A §16 "the most real files at one address being 50": at most 3 distinct 2xx bodies and 6 source files sit at any top-level URL today, 455 at one placeholder caption URL **[spec7_measure2.py]**; the 50 counts archive members at their container's address (the reconciliation's predicate). Say "address, members included".
13. DM §7.10 "its largest listed document has 27": the largest document-role catalog row without a placeholder body has 44 distinct capture URLs and 33,479 occurrence structs **[spec7_measure2.py]**; name the predicate.
14. DM §6.1 "62% of older successful pages declare none": 76% by my predicate (no `content-length` and no chunked header on 97,061 2xx HTML lines; 23,171 of the 23,182 that declare one also carry `content-encoding`) **[spec7_scan_receipts.py]**. The direction holds; the figure depends on which header copies are read.
15. DM §7.7 "19,316 requested URLs today" with no time: 25,843 by a seven-field scan **[measured]**; plausible once the mapping reads more fields, but the predicate should sit with the number.
16. DM §7.8 "3,558 of 11,044 recovery bodies": 4,563 of 11,393 by receipt-key pattern **[spec7_measure.py]**; same order, receipt-mode predicate not reproducible from the snapshot.
17. A §12 Budgets: publish "refuses at once" when a step exceeds its budget and the backfill is "on demand"; say who starts it.

## 3. Review-6 status

| R6 | Finding | Status | Where |
|---|---|---|---|
| M1 | `complete` undefined without a declared length | RESOLVED | DM §5.2 `complete` (l.131); older lines DM §6.1 (l.219); fixtures P l.129–130 |
| M2 | "source URL" undefined; ZIP link matched every member | RESOLVED | DM §3 (l.57–58); `copy_urls` (l.388–390); Matching (l.399); §7.10 (l.627–628) |
| M3 | `receipts/` locked while old writers still write cookies and paths | RESOLVED | P §4 table (l.70); B0 "First, stop the old writers" (l.185) |
| S1 | Record-role grain | RESOLVED | DM §7.3 "per capture row" (l.414); §7.4 (l.468); inv. 8 (l.730) |
| S2 | §7.4 step 1 vs §7.8 decision match | RESOLVED | DM l.475; l.607 |
| S3 | `document_id` not today's | PARTLY | Formula unchanged (l.538); P E4 (l.269) names web pages; the data shows the same shape with a different "real" predicate (minor 11 above) |
| S4 | List and fold order | RESOLVED | DM l.583 |
| S5 | HTML page versions multiply documents | RESOLVED by decision | decisions.md "main content"; DM §3, §6.2 (l.256); P fixture l.120; the reconciliation's 7.3 shows 2,696 of 3,736 pairs are identical text |
| S6 | `same_rendition (b)` "otherwise"; unlisted formats; stem case | RESOLVED | DM l.502–503; l.515 |
| S7 | Invariant 13 vs §7.8 | RESOLVED | DM l.735; l.612 |
| S8 | `saved_media_type`; older `complete`; B13 candidates | PARTLY | first two DM l.524, l.219; B13 candidates still unnamed (S4 above) |
| S9 | "meeting page"; "at most 9" | RESOLVED | DM §3 (l.69); §8.1 "usually empty or one" (l.649) |
| S10 | `next_attempt_at` with null `last_attempt` | RESOLVED | DM l.597 |
| S11 | Numbers that did not reproduce | PARTLY | 4,000–8,000 ops (A l.522), 2,467 (P l.297), 34,446 (DM l.455) and 103,200 (DM l.547) now reproduce; 579 (A l.441) unchanged (588 MiB / 642 MB measured); "27" and "50" carry unnamed predicates (minors 12–13) |
| S12 | `linked_from` vs `publisher_links` on members | RESOLVED | DM l.399; l.628 |
| S13 | B14 on the capped old path | RESOLVED | P l.204 "(after B2, through the spooled fetcher)" |
| minor | 2,048-byte constant; `committee_key` grain; empty-filename fallback; nullability; release-ID field list; bindings rows | RESOLVED | DM registries l.347; l.566; l.474; §6.1 table; §8.3 l.673; B raw-verifier and workflows rows |
| minor | `locator` twice; fixture 2's input; "enters the queue"; JSON default role; scanned PDFs; HEAD failure; inclusive date | OPEN | unchanged text; all minor |

The reconciliation marked my review-6 `document_id` finding refuted ("same formula; today's inputs exclude web pages") and the page-version finding refuted as stated. The first is right for listed formats (minor 11); the second is right on the data and is now settled by the owner's decision.

## 4. The lead's claims

| Claim | Verdict | Evidence |
|---|---|---|
| Grade about 87 | PARTLY | 85 here; the gap is S1–S4, which the lead did not list. 87 is defensible once S1–S4 are folded (four one-line edits, two of them deletions). |
| Raw-data safety 9.5 | AGREE | Create-only writes, 412 semantics, lock order, backup-before-rewrite, re-hash before the first check all stand in the text; the B13 miss (S4) is a data-quality, not raw-safety, cost. |
| Grounded in data 9.5 | PARTLY | Principle 9 and most citations hold; but five figures carry no predicate or do not reproduce (minors 12–16) and D1's time count contradicts a seven-field scan (S5). 8.5. |
| Internal consistency 9, "no contradictions found" | DISAGREE | Two: A §11.1 "no dictionary page beneath it" versus DM §8.1 "dictionary encoding only on `dict` columns" in ranged files (S2); and `list`'s `format`, `congress`, `document_family` have no derivation (S1). 8. |
| "193 references, 0 problems" | AGREE | My own checker resolves 303 section and plan-item references with no real miss **[spec7_xref.py]**; its 13 flags are list continuations such as "DM §5.3, §7.9" and RFC 3986 §6.2.2. |
| Executable plan 8.5; M1 and M2 open | AGREE | P §5.1–5.2 are decision gates with named outcomes; nothing above raw can be sized before them. |
| Simplicity 7 | PARTLY | 7.5: the grouping rules are intricate, but each clause answers a settled decision (editions apart; one entry across formats; members judged by path), and the order of evaluation (DM l.543) now makes them computable in one pass. |
| Readability and concision 7 | AGREE | DM 9,929 words, all four 27,835 **[measured]**; A §7.1's fetching paragraph and DM §7.7's queue sentence each carry four clauses and two numbers. |
| Holds back 1: the grouping model is checked only on fixtures | AGREE | P §5.3 already requires S1 to run as an executable model over fixture tables; the lead's remedy adds a real-data slice, which the plan lacks. |
| Holds back 2: ceremony in P §3 | PARTLY | The ticket-before-commit and `wc -l` rules match the owner's working rules, so they are not the editor's to cut; the epic and acceptance-criteria sentences are the boilerplate the lead means. The self-correction on W3C framing is right (decisions.md). |
| Holds back 3: density | AGREE | Word counts above. |
| Nit: A §6 diagram omits bodiless-line rows | AGREE | A l.183 reads "one row per body a receipt line references" **[grep]**. |
| Nit: P §1 "carries `stored_sha256`" | AGREE | P l.29 and B12 (l.202) both say it; it is the old path, and a reader of DM §6.1 ("no `stored_sha256`") stumbles. Write "today's index carries". |
| Raise 1: run S1 now, and on real data | AGREE | Add the real-data slice to P §5.3's sentence. |
| Raise 2: cut boilerplate; concision pass on DM §7 | PARTLY | Cut the two P §3 sentences; DM §7's length comes from rules the decisions require, so the pass should remove numbers without predicates before prose. |
| Raise 3: run M1 and M2, re-grade after | AGREE | — |
| Already checked: no body ETag contains `-` | AGREE | Six HEADs on the public bucket, three bodies over 1 GB, all 32-hex ETags without `-` **[spec7_etag_head.py]**. |

**What the lead missed:** S1 (a regression from the concision pass), S2 (a contradiction created by fix 3.2 of the reconciliation, which changed the writer without re-checking A §11.1 and C3, the very pattern root cause 1 names), S3, S4 (the sniff rule from fix 1.8 made a copier miss permanent), S5, and the unnamed predicates behind "27", "50", "62%", "19,316" and "3,558 of 11,044".

## 5. Data checks

| Check | Script | Result |
|---|---|---|
| Today's `document_id` rule over all subsets of body keys and member source_ids | `spec7_ids.py` | 8,000 docs: 33% bodies(all), 3% bodies(subset), 50% sources(all); unmatched 14% are rows whose member lists are null (the doc's own source_id then matches, per review 6) |
| Same, by format and capture state, single-body document rows | `spec7_ids_format.py` | 10,000 rows: bodies 37%, sources 62%; sources = captions 3,653, HTML 1,128, untyped 584, playlists 66, XML 77, PDF 12; bodies = PDF 2,414, XML 874, ZIP 47 |
| PDF copier candidates | `spec7_measure.py` | media-type rule 261,056 bodies; 34,329 of them not PDF by the old sniff; 69 old-sniff PDFs outside it; 73,644 bodies have no media type on any row (49 with a `.pdf` locator) |
| Recovery bodies also fetched normally | `spec7_measure.py` | 4,563 of 11,393 by receipt-key pattern (DM: 3,558 of 11,044) |
| Untimed rows in dated receipts | `spec7_measure2.py` | 522,448 exactly (regex on the receipt key) |
| Time fields on receipt lines, URLs without a time, declared lengths | `spec7_scan_receipts.py` | 2,596,054 lines; times on 1,313,731 lines (`retrieved_at` 802,271, `captured_at` 452,186, `observed_at` 29,024, `checked_at` 21,874, …); 35,970 dated-prefix entries with no time; 25,843 fetch URLs with no time on any line; 2xx HTML: 23,182 declare a length (23,171 content-encoded), 295 chunked, 73,584 neither |
| HTML members at successful ZIP URLs | `spec7_measure.py` | 34,446 rows = 34,446 endpoints = 34,443 bodies |
| Most bodies and source files at one top-level address | `spec7_measure.py`, `spec7_measure2.py` | 3 bodies; 6 source files (455 at a placeholder caption URL) |
| Largest document-role catalog row without a placeholder body | `spec7_measure2.py` | 44 distinct capture URLs; 33,479 occurrence structs |
| Last status 404/410 | `spec7_measure.py` | 36,854 by first status (P: 36,768) |
| GovInfo metadata files listed as documents | `spec7_measure.py` | 103,883 by name (DM: 103,200) |
| Committed page-versions comparison | `spec7_pageversions.py` | 134 PDF/XML addresses, 126 with an unfingerprintable (cut-off) version, 1 with equal fingerprints |
| Cross-references | `spec7_xref.py` | 303 resolved; 13 regex artifacts, 0 real misses |
| Body ETags on the public bucket | `spec7_etag_head.py` | 6 HEADs (3 over 1 GB): all plain 32-hex, no `-` |
| Word counts | inline | A 6,906; DM 9,929; P 5,802; B 5,198 |
