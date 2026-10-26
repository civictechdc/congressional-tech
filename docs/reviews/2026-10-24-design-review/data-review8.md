# Review 8 (data lens): docs/engine-first-data-model.md @ 33c2cba0

Reviewer: independent, unanchored (did not read docs/reviews/). Lens: are the document's factual claims true of the real data and code?

## 1. Score

**70 / 100. Confidence: medium-high.**

The counts are unusually good. Of the numbers I could re-derive, most match to the unit or within snapshot drift. Examples: 2,596,054 lines; 3,908,849 rows; 1,041,863 bodiless lines; 1,036,256 bodies; 99 list-valued records; 123 `publisher_requested` lines; 287,765 HTML/XML bodies; 11,792 recovery bodies; 18 placeholders at k = 100; and the 57-byte caption at 87,161 URLs.

Where the document falls down is the **shape** of older receipts, which its rules depend on:

- The Congress.gov meeting records exist only as inline receipt JSON, not as bodies.
- More than half of the recovery lines carry no `prior_access_category`, and a third carry no `recovery_evidence.original_url`.
- `original_path` sits on half a million non-archive file references as a local path.
- Senate caption and Congress.gov meeting lines keep their time under field names the mapping does not list.

Each of these would make a MUST rule fail the build or produce wrong rows. One markdown defect also hides §7.11's notes, all of §8 and the §9 heading from rendering.

Snapshot caveat: the receipts mirror was copied on 2026-10-23. Its line count equals the document's 2,596,054 exactly, so it is effectively the document's snapshot. The local index and catalog parquets date from 2026-10-02 and 2026-10-13, and I treated small differences against them as drift.

## 2. Claims table

How I checked: I extracted every receipt line under `.cache/docspec-catalog/r2-immutable/receipts/` (2,289 files) with my own streaming parser into per-row parquet: one row per `captures[]` entry, else per `file_references[]` entry, else one per line. I queried it with DuckDB. Scripts are in `review8/data/scripts/r8d_*.py`. The spicy-regs tables were downloaded from the `publication.v2.json` prefixes into `review8/data/dl/`. Verdicts: **C** = confirmed, **W** = wrong, **U** = unverifiable, **C~** = consistent within drift or a looser definition.

| # | Claim | § / line | Method | Result | Verdict |
|---|---|---|---|---|---|
| 1 | Every older body key is `…/<sha>.gz` | §5.1 L105 | Compared `body_key` with `bodies/sha256/<aa>/<sha>.gz` on every row | 0 mismatches | C |
| 2 | 1,036,256 bodies | §5.1 L110 | Distinct `sha256`, and separately distinct `body_key` | 1,036,256 and 1,036,256 | C |
| 3 | 0.70 TB stored | §5.1 L110 | Sum of max `stored_bytes` per body | 0.696 TB (364,193 bodies have no `stored_bytes`, so this is a lower bound) | C~ |
| 4 | Largest 1.19 GB; none above 5 GB | §5.1 L110 | max(`stored_bytes`) | 1,188,171,429 | C |
| 5 | 61 multipart `.gz` bodies over 200 MiB | §5.1 L107 | Needs R2 ETags | 169 bodies have `stored_bytes` > 200 MiB; I cannot tell which were multipart | U |
| 6 | About 260,175 `.pdf` copies, about 403 GB | §5.1 L105 | Needs an R2 listing. Proxy: bodies labelled PDF by media type or URL | 323,315 bodies, 444 GB original size (a label, not a sniff) | U |
| 7 | No older line records an MD5 | §5.1 L109 | Key survey of all entry shapes | Entries carry `stored_sha256` and `stored_bytes`, never an MD5 | C |
| 8 | `captures[]` median 1, max 5,806 | §5.2 L134 | Per-line `len(captures)` over lines with captures | Median 1, max 5,806. `file_references[]` reaches 22,354 | C |
| 9 | 123 older import lines say `publisher_requested` true | §5.2 L162 | Count over `mode = retained_import` lines | 123 of 12,106 | C |
| 10 | `recovery_evidence.acquisition.prior_access_category` gives the display kind | §5.2 L166, §6.1 L246, §7.8 L722 | Walked every key of `recovery_evidence` on all 12,106 import lines | Present on 5,587 (46%). 839 have only `acquisition.category` (`pdf`, `html_metadata_only`…: a format, not a category). 5,542 have only `acquisition.kind` (`pdf`, `html`, `xml`). 138 have neither | W |
| 11 | `recovery_evidence.original_url`, `.imported_at` and `.match_basis` are on recovery lines | §5.2 L163–165 | Same walk | Missing on 4,286 of 12,106 (35%). Their link is in `record.source_associations[].original_url` (4,286) and in `acquisition.original_url` (4,148) | W |
| 12 | `acquisition.body_path` on older lines is a local path | §5.2 L167 | Count and pattern | 11,968 of 12,106. Many last segments are hash names (`<sha>-1.body`, `.decoded`) | C |
| 13 | The one-time cleanup removed cookies, credentials and local paths | §5.2 L177–181 | Scanned the 2026-10-23 mirror | 221,362 lines in 161 receipts still hold `/Users/…` paths; 137 lines in a 400-file sample still name cookie or authorization headers. Either the mirror predates the cleanup or the cleanup has not run | U |
| 14 | `original_path` appears on an archive member's entry only | §5.2 L144 | Grouped entries by whether the pointer passes through `archive_members` | `captures[]`: only on members (171,894). `file_references[]`: 522,501 non-member entries carry it, 279,264 of them absolute local paths | W |
| 15 | 1,041,863 of 2,596,054 lines have no body | §6.1 L226 | Lines whose rows all have a null sha | 1,041,863. One of them has a file reference with no sha (1,041,862 have no entries at all) | C |
| 16 | Every line today is an older line | Abstract L12, §6.1 L251 | Top-level key survey | Only `captures`, `file_references`, `download_state`, `record` and `source_*` shapes exist | C |
| 17 | 2.96M of 3.9M rows carry no outcome | §6.1 L256 | Count | 2,963,651 of 3,908,849 | C |
| 18 | Outcomes such as `saved`, `html`, `captured`, `http_error`; most rows have no mode | §6.1 L256 | Value counts | 42 outcome values; 2,991,645 rows have a null mode; 13 mode values (`native_live`, `replay`, `zyte`, …) | C |
| 19 | A body of exactly 64 MiB is a cut-off | §6.1 L258 | Histogram of `bytes` between 60 and 70 MB | A spike of 207 rows (201 bodies) at exactly 67,108,864 | C |
| 20 | About 61% of 2xx HTML responses with full headers declare no length; nearly all others name an encoding | §6.1 L258 | `response_headers` shape, 2xx, HTML | 60.9% have no length; 99.9% of the rest carry `content-encoding` | C |
| 21 | Fetch time comes from `retrieved_at`, or `captured_at` on Senate caption runs | §6.1 L259 | Time-key presence by receipt prefix | `senate/captions` has 1,384,330 rows: 452,186 carry `captured_at`, about 13,844 lines carry `observed_at`, and most carry neither at line level. The 199,156 `congress/meetings` lines carry `_retrieved_at` and `_url` | W |
| 22 | 99 list-valued `record` lines | §6.1 L262 | Count | 99 | C |
| 23 | "2.7M time-less rows are mostly caption segments whose lines carry `captured_at`" | §7.5 L655 | Rows without `retrieved_at`, split by other time keys | 2,668,607 rows (≈ 2.7M, correct). Only 452,186 carry `captured_at`; 2,216,421 carry no time at all (923k Senate caption, 899k `documents/undated`, 199k `congress/meetings`) | W |
| 24 | 287,765 bodies the server labels HTML or XML | §6.2 L301 | Distinct sha where the entry's `media_type` contains html or xml | 287,765 | C |
| 25 | 277,642 contexts over 214,041 good-fetched HTML/XML bodies | §7.2 L487 | Rough good-fetch filter (2xx, saved, not import) | 288,321 contexts over 226,735 bodies (ratio 1.27 against 1.30) | C~ |
| 26 | k = 100 gives 18 placeholders; 22 at 50, 12 at 200; widest is a 57-byte caption at 87,161 URLs | §7.3 L550 | Distinct `context_url` per body | 18 at 100; **20** at 50; **11** at 200; widest 57 bytes, `text/vtt`, 87,161 | C (k = 100), W (minor, at 50 and 200) |
| 27 | 34,331 HTML members at good-fetched ZIP URLs | §7.3 L541 | Archive-member entries ending `.htm`/`.html` | 34,446 members in 34,311 ZIPs, before the good-fetch filter | C~ |
| 28 | 34,196 good-fetched GovInfo ZIPs; 112 are HTML only | §7.2 L491, §7.5 L653 | ZIP URLs with 2xx; per-ZIP member formats | 34,440 2xx ZIP URLs (271 of them `size_limit`); exactly 112 ZIPs have HTML but no PDF | C~ / C |
| 29 | 331,985 filename rows have `''` as source URL | §6.3 L317 | 10-13 catalog `document-filenames` | 331,231 | C~ |
| 30 | 24,202 / 3,637 / 5,229 source files have more than one kind / family / committee code | §6.3 L321 | 10-13 catalog | 24,243 / 3,730 / 5,221 | C~ |
| 31 | 1,392,681 `(filename, source URL)` pairs | §6.3 L333 | 10-13 catalog, distinct pairs | 1,383,756 | C~ |
| 32 | 1,683,430 source files | §7.4 L554 | 10-13 catalog rows | 1,672,092 | C~ |
| 33 | 1.24M catalog rows; 454k caption snippets; 10k playlists | §7.5 L654 | 10-13 catalog | 1,235,122; 453,751 `.vtt`; 10,926 `.m3u8` | C |
| 34 | `publication.v2.json` is current; the older `publication.json` names pruned generations | §6.4 L338 | Fetched both; HEAD on two old-index files | Old prefixes return 404; v2 prefixes serve | C |
| 35 | The spicy-regs columns the model reads (all 9 tables) | §6.4 L340–350 | Column lists in `publication.v2.json`, and in the files themselves | Every named column exists (`history` has `officialName`, `startDate`, `endDate`) | C |
| 36 | 422,011 measures from the 6th Congress, keyed `{congress}-{type}-{number}` lowercase | §6.4 L346, §6.3 L325 | `congress_bills` | 422,011 rows, unique; Congresses 6–119; 0 rows differ from the formula | C |
| 37 | CBO estimates, about 1,100–1,700 a Congress | §6.4 L347 | Group by Congress | 913–1,666, and only from the 108th. The 109th (1,031), 111th (1,087) and 112th (913) fall under 1,100 | W |
| 38 | Roll-call votes: House from the 101st, Senate from the 108th | §6.4 L348 | min/max by chamber | House 101–119 (22,511); Senate 108–119 (8,191) | C |
| 39 | `documents` carries a nomination's `PN{number}[-{part}]` | §6.4 L348 | Unnested `documents` | 3,990 `PN` entries, Senate only (for example `PN246-13`). House votes have none | C |
| 40 | Nominations cover the 119th Congress only | §6.4 L350 | Group by Congress | 2,287 rows, all 119th. `part_number` is zero-padded (`'08'`, and `'00'` when there is no part); `citation` is unpadded (`PN13-8`) | C (the key form is underspecified) |
| 41 | Committee seats cover the current Congress | §6.4 L345, §7.11 | Group by Congress | All 2,973 rows are 119th | C |
| 42 | Members since 1789 | §6.4 L343 | `member_terms` | 12,770 members; first term starts 1789-03-04 | C |
| 43 | `bill_vote_references` gives floor votes a bill's actions name | §6.4 L349, §7.11 | Joined to `roll_call_votes` | All 19,766 rows join, but only by building `vote_id = congress-chamber-session-roll`, which the document never states | C (join key unstated) |
| 44 | Transcript jackets come from `hearingTranscript[].jacketNumber` | §6.5 L373 | Parsed `congress/meetings` records | 183,056 entries shaped `{jacketNumber, url}` | C |
| 45 | The Congress.gov meeting JSON lists no Senate witnesses | §6.7 L408 | Records with `witnesses`, by chamber | House 91,062; NoChamber 14; Senate 0 | C |
| 46 | Congress.gov meeting JSON is a response body that the JSON parser reads (`body_sha` keys) | §6.5 L360, L377–378; §6.7 L389; §10 inv. 5 | Bodies per receipt prefix; `api.congress.gov/v3/committee-meeting/…/{id}` bodies | 199,156 meeting records sit **inline** in receipt lines (`_url`, `_retrieved_at`, `eventId`, `hearingTranscript`, …); 198,946 of those lines reference no body. Only 15 committee-meeting JSON bodies exist | W |
| 47 | docs.house.gov and Congress.gov share the meeting ID | §6.5 L363 | IDs from both URL patterns | 7,239 of 8,949 docs.house.gov IDs appear in congress.gov URLs | C |
| 48 | Meeting URL patterns; `HHRG`/`HMKP`/`HMTG` prefixes | §7.5 L664–670 | Regex over every URL | All 183,517 docs.house.gov meeting URLs match; 168,017 congress.gov meeting URLs match; filename prefixes are HHRG, HMKP and HMTG, plus CRPT/HRPT documents | C |
| 49 | AG03 → `hsag03`, IG00 → `hlig00` | §7.5 L675 | `committees` | Both system codes exist | C |
| 50 | `CHRG-{congress}{h\|s}hrg{jacket}`, with a joint case | §7.11 L754 | Package IDs in URLs | 20,605 `hhrg`, 13,401 `shrg`, 775 `jhrg` | C |
| 51 | Compact JSON equals Python `json.dumps(…, ensure_ascii=False, separators=(",",":"), allow_nan=False)` | §3 L85 | Ran it over all control characters, `"`, `\`, `/`, é, U+2028, U+007F | Output matches the stated escapes | C |
| 52 | YouTube caption URLs carry a constant `key` | §7.1 L452 | `key=` values by host | Only www.youtube.com, with 1 distinct value | C |
| 53 | `retry_later` is a 429 or 503 or a `Retry-After` | §5.2 L127 | Status of `retry_later` lines | All 79,112 are 503. Their hint is `record.retry_later.delay_seconds`, not a header | C (the source of `retry_after` is unmapped) |
| 54 | No fingerprint candidates among PDF/ZIP bodies | §6.2 L302 | Endpoints with ≥ 2 distinct 2xx PDF/ZIP-labelled bodies | 4,882 found; 4,755 are explained by End of Term `["eot","raw_warc","body"]` envelopes (which sniff as `warc`); the remaining 127 are second bodies within one line (likely prior attempts) | C~ |
| 55 | 11,792 recovery bodies, 3,690 of them also real bodies | §7.8 L724 | Distinct sha on import rows; overlap with non-import rows | 11,792; at most 4,335 overlap (an upper bound before the real-file filter) | C / C~ |
| 56 | Older receipts include 49 undated or mixed-date files with 1,257,667 lines (the work-list premise) | §6.1 L264 → ARCH §8.2 | Keys without a date segment | 49 files, 1,257,667 lines | C |
| 57 | `captures.requested_url` and `url` are non-null strings; `family` is non-null | §6.1 L227–228 | Lines with neither field at record top level | About 0.55M lines (240,821 are `{original_path}`-only bundle lines; 44k are MODS records). 1.42M body rows have no family in entry or record | W |
| 58 | About 0.8% of documents with a real file have no capture date (4,681 of 561,791) | §7.5 L655 | Non-caption bodies with no time field on any row (looser filter) | 14,659 of 658,018 (2.2%) | U |
| 59 | `url_state` has 1,158,426 rows; about 25,500 requested URLs have a null `last_attempt` | §7.7 L708, L711 | Distinct requested-or-final URL on non-import lines | 1,172,637 using `record.url` only; 7,388–34,851 undated, depending on which time fields count. Both depend on the mapping | U |
| 60 | Release writer settings (dictionary only on `dict` columns, 64 KB pages, batches of 1,024, `DELTA_BYTE_ARRAY`, pinned `created_by`, flush on row count only) | §8.1 L797–802 | `docspec-rs/src/engine/export/pipeline.rs` `build_writer_properties` | The engine today enables dictionary on every column, uses 1 MB pages (16 KB only on page-index columns), batches of 256, caps row groups by bytes too, and sets no per-column encoding or `created_by`. ARCH line 505 lists this as engine work | C (a requirement, not current behavior) |
| 61 | Role sample of 3,021 pages; rendition groups (~560 / 732); `readings` size (491,710 rows, 16.5 MB); `captures` size (157 MB) | §7.3 L549, §7.5 L653, §6.2 L308, §6.1 L265 | — | No labelled sample, no reading parts (outside my allowed paths), and no lake build | U |

Totals over 61 claims: **confirmed 46** (C and C~), **wrong 9** (#10, 11, 14, 21, 23, 26, 37, 46, 57; #26 counts as wrong for its k = 50 and k = 200 figures), **unverifiable 6** (#5, 6, 13, 58, 59, 61). The markdown defect (F5) is a finding, not a claim.

## 3. Findings (most severe first)

### F1. Major: Congress.gov meeting records have no body, yet `meeting_records` and `appearance_records` are keyed on one
- **Where:** §6.5 L360, L377–378; §6.7 L387–389; §10 invariant 5.
- **What is wrong:** The document treats "the Congress.gov meeting JSON" as a response body that the JSON parser reads, with `body_sha` as "the response" and a completion row per body. In raw, the 199,156 Congress.gov meeting records are the receipt lines themselves.
  - They sit under `congress/meetings/…`, with keys `_url`, `_retrieved_at`, `chamber`, `eventId`, `hearingTranscript`, `videos`, `witnesses`, `meetingDocuments`.
  - 198,946 of these lines reference no body.
  - Only 15 `api.congress.gov/v3/committee-meeting/{c}/{ch}/{id}` bodies exist.
- **Why it matters:** All Senate meeting records (50,301) and the jacket numbers exist only there. A body-keyed producer yields none of them, and invariant 5 cannot see the gap because it ranges over responses "a producer has read".
- **Evidence:** `r8d_q.sh` queries over `congress/meetings%`: 199,156 rows, 15 with `url`, 198,946 with no sha. The meeting parse (`r8d` inline script) found `hearingTranscript` on 183,056 records.
- **Fix:** Rewrite §6.5 Sources and PK as: "Sources: a Congress.gov meeting record is either a response body or, on older lines, the receipt line's own `record` (inline JSON); its source key is `body_sha` for a body and `(receipt_key, receipt_line)` for an inline record. PK: `(source_key, parser_version, chamber, event_id)`." Make the same change to §6.7's PK, and to invariant 5 ("every meeting body or inline meeting record…").

### F2. Major: 54% of recovery lines carry no `prior_access_category`, and §7.8 then fails the build
- **Where:** §5.2 L166; §6.1 L246; §7.8 L722.
- **What is wrong:** §7.8 says "A row with no category takes its decision's kind. An unmapped category, or a row with neither, MUST fail the build."
  - Of 12,106 import lines, only 5,587 carry `acquisition.prior_access_category`.
  - 839 carry `acquisition.category`, and 5,542 carry only `acquisition.kind`. Both hold format values (`pdf`, `html`, `xml`, `html_metadata_only`), not display categories.
  - 138 carry neither.
- **Consequence:** Unless provenance `recoveries` decisions exist for about 6,519 lines, the first publish fails. The document does not say that this provenance exists, or how many records it holds.
- **Fix:** In §6.1, define `recovery_category` as "the receipt's `acquisition.prior_access_category`; null otherwise (6,519 of 12,106 older lines)". In §7.8 Kind, state the fallback that is actually intended, for example: "A row with no category takes its decision's kind, else `recovered_document` when `match_basis` is `verified_archive_capture` or `user_accepted_url_variant`, or when it has no match basis…". If the intent really is to require decisions, rewrite the sentence so that the backfill job writes the 6,519 decisions before the first publish.

### F3. Major: 35% of recovery lines have no `recovery_evidence.original_url`, `imported_at` or `match_basis`
- **Where:** §5.2 L163–165; §6.1 L246; §7.8 L715–723; §8.1 `recoveries.parquet` (`imported_at date32`, not nullable).
- **What is wrong:** 4,286 of 12,106 lines lack all three fields. Their original link is in `record.source_associations[].original_url` (all 4,286) and in `acquisition.original_url` (4,148, always equal to it). These lines do have `record.retrieved_at`.
- **Consequence:** The decision match ("`original_url` equals the row's as an exact string"), the attachment rule, link URL keys and the recovery order would all see a null for a third of recoveries. The release's non-null `imported_at` would then fail to write.
- **Fix:** In §5.2, rewrite the `recovery_evidence.original_url` row as "The link this content recovers. Older lines without it: `record.source_associations[0].original_url`." Make `imported_at` "RFC 3339, nullable on older lines (4,286)". In §6.1, write `original_url` as `coalesce(recovery_evidence.original_url, source_associations[0].original_url)`. In §8.1 and §7.5, make `imported_at` "date32 nullable", with the recovery order reading `imported_at desc nulls last`.

### F4. Major: `original_path` is not limited to archive members
- **Where:** §5.2 L144 (`member_path` row); §6.1 L233.
- **What is wrong:** The claim "Older lines: `original_path`, on an archive member's entry only" holds for `captures[]` entries (171,894, all members). But 522,501 `file_references[]` entries also carry `original_path`, and it is a retained file's local path. 279,264 of them are absolute (`/Users/…/hearing-text/…`, `raw-source-backfill-…/bodies/<sha>.gz`).
- **Consequence:** §6.1 maps `file_references[]` entries into `captures`. A mapping that follows §5.2 would mint 522k fake archive-member paths. Effective-filename rule 2 ("the member basename") would then name those files `<sha>.gz`, split their endpoints, and give an apparent member path to bodies with no container.
- **Fix:** Rewrite the §5.2 `member_path` note as: "Older lines: `original_path` on a `captures[]` entry whose `pointer` passes through `archive_members`; a `file_references[]` entry's `original_path` is a retained-file path and is never a member path."

### F5. Major (document integrity): a stray code fence hides §7.11's notes, all of §8 and the §9 heading
- **Where:** L782–784.
- **What is wrong:** Line 782 closes the §7.11 code block, and line 784 opens a new, empty one. A closing fence cannot carry an info string, so the ```` ```mermaid ```` at L849 does not close it. Everything from L784 to L879 renders as one code block: the §7.11 bullets, the §8 heading, the §8.1 table and writer profiles, §8.2, §8.3 and the §9 heading.
- **Evidence:** `markdown_it` (CommonMark) parse gives fence tokens [459–480], …, [750–782] and **[783–879]**. The only headings rendered after line 780 are at L891, 925, 927 and 950. The table of contents links to §8 and §9 are dead.
- **Fix:** Delete line 784, and line 785 with it, so the bullets at L786–787 follow the §7.11 code block.

### F6. Minor: time fields the mapping does not name, and a wrong explanation of the time-less rows
- **Where:** §6.1 L259; §7.5 L655.
- **What is wrong:**
  - Senate caption lines (1,384,330 rows) mostly carry no `captured_at`; some carry `observed_at`.
  - Congress.gov meeting lines carry `_retrieved_at`.
  - YouTube and MODS lines carry `started_at` and `checked_at`.
  - The L655 explanation ("2.7M time-less rows are mostly caption segments whose lines carry `captured_at`") contradicts itself: a row with `captured_at` would not be time-less after mapping. In the data, 2,216,421 of 2,668,607 rows carry no time field at all.
- **Fix:** Rewrite L259 as: "takes the fetch time from `retrieved_at`, else `captured_at`, else `_retrieved_at` (Congress.gov meeting lines), else `observed_at` (Senate caption lines), else null; on End of Term archive fetches…". Rewrite L655's parenthesis as: "the snapshot's 2.67M rows without `retrieved_at` are 0.92M Senate caption segments, 0.90M undated document-bundle rows and 0.2M inline Congress.gov meeting records, of which 0.45M carry `captured_at`".

### F7. Minor: the CBO coverage figure is wrong
- **Where:** §6.4 L347.
- **What is wrong:** Per Congress the table holds 913–1,666 estimates, and only from the 108th Congress.
- **Fix:** "CBO cost estimates from the 108th Congress, about 900–1,700 a Congress".

### F8. Minor: unstated key normalizations for nominations and floor votes
- **Where:** §6.4 L349–350; §7.11 L776–781; §6.5 L372.
- **What is wrong:**
  - `nominations.part_number` is zero-padded, with `'00'` when there is no part, and `citation` is unpadded (`PN13-8`). The key `{congress}-pn-{number}[-{part}]` does not say which form to use.
  - `bill_vote_references` has no `vote_id`. Joining it needs `{congress}-{chamber}-{session}-{roll_number}`, which matches all 19,766 rows.
- **Fix:** In §6.5, write the nomination key as "`{congress}-pn-{number}[-{part}]`, `part` without leading zeros and omitted when `part_number = '00'` (the form of spicy-regs `citation`)". In §6.4, add `vote_id` to the "Gives" cell of `bill_vote_references`: "Floor votes a bill's actions name, as `vote_id = {congress}-{chamber}-{session}-{roll_number}`, that the vote's own record may not".

### F9. Minor: `captures` declares columns non-null that older lines cannot fill
- **Where:** §6.1 L227–228.
- **What is wrong:** About 0.55M lines have neither `url` nor `requested_url` (bundle lines that hold only `original_path`, and MODS records). The 199k meeting lines have only `_url`. 1.42M body rows carry no family in either entry or record.
- **Fix:**
  - Type `requested_url, url` as "string, nullable; `_url` on inline-record lines".
  - Type `family` as "string; older rows take it from the receipt key's `<family>` segment".

### F10. Minor: the older retry hint is not a `Retry-After` header
- **Where:** §6.1 L236.
- **What is wrong:** All 79,112 `retry_later` lines (25,236 distinct GovInfo ZIP URLs) carry `record.retry_later = {delay_seconds, reason}`.
- **Fix:** "The `Retry-After` deadline, or on older lines `retry_later.delay_seconds`, resolved against `retrieved_at`."

### F11. Nit: the placeholder threshold comparison has drifted
- **Where:** §7.3 L550.
- **What is wrong:** k = 50 gives 20 bodies, not 22; k = 200 gives 11, not 12. The k = 100 figure and the widest body match.
- **Fix:** "(20 at 50, 11 at 200)".

### F12. Nit: the reference-count range covers `captures[]` only
- **Where:** §5.2 L134; §6.1 L226.
- **What is wrong:** Older `file_references[]` reaches 22,354 per line. One line has a file reference with no sha (`resolution: retained_as_receipts`), which becomes a null-sha row at `capture_index` 0 with a reference.
- **Fix:** At L226, write "0, with a null `sha256`, on the row of a line without a body (1,041,863 of 2,596,054 lines, one of them a bodiless file reference)".

### F13. Nit: the Congress.gov chamber value `NoChamber` is not mapped
- **Where:** §6.5 L362; §7.11 L752–755.
- **What is wrong:** 1,828 meeting records have `chamber = NoChamber`, and the values are capitalised (`House`/`Senate`). The meeting key `chamber:event_id` and the transcript chamber rule do not say how to normalise them.
- **Fix:** In §6.5, define `chamber` as "`house`, `senate` or `joint` (Congress.gov `NoChamber`), lowercase".

## 4. What I could not check, and why

- **R2 object facts:** multipart ETags (the 61 bodies), `.pdf` copy counts and sizes, `Content-Type` and `Content-Encoding` of older objects, and verification records. I had no bucket access, only a receipts mirror.
- **Whether the receipt cleanup has run:** the mirror dated 2026-10-23 still holds local paths and cookie header names (#13). I cannot see the bucket's current bytes.
- **Provenance (`provenance/recoveries`, `url_variants`, `reviews`):** no local copy. This decides whether F2 is a live build failure or only a documentation gap.
- **Reading-derived figures:** link counts, `text_bytes`, fingerprints, the role sample, rendition-group counts and `readings` size. Readings sit under `docspec-catalog/reading-parts`, outside the allowed paths, and body bytes were not available.
- **Mapping-dependent counts:** `url_state` rows, null `last_attempt`, and no-date document shares. They depend on mapping decisions the document leaves open, so I report ranges only.
- **Prior-attempt bodies:** I could not confirm whether the 127 remaining multi-body PDF/ZIP endpoints (#54) are all cut-off attempts, because older lines record no per-attempt completeness in my extraction.
- **Blind spots of my method:** my extractor reads `record` top-level fields, plus the first element of a list-valued record, and the entry fields. It does not see URLs nested in `redirects`, `prior_attempts` or provider metadata, so the credential-parameter check (#52) covers top-level URLs only. Media-type labels stand in for sniffed formats in #6, #24 and #54, so a sniff could move those counts.
