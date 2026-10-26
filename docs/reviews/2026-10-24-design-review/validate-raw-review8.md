# Review 8: raw-data validation of A1–A14, E2, E3, E6

Spec: `docs/engine-first-data-model.md` @ 33c2cba0. Evidence: the receipts mirror (2,289 files, 2,596,054 lines, 3,908,849 rows), the 2026-10-02 index parquets, `packages/` code, and the spicy-regs `bill-family` generation `1f457ce1…` (published 2026-10-26; the file's SHA-256 matches the index).

**Method.** I did not reuse any reviewer script, parquet or number. Every count comes from my own streaming pass over the raw gzip lines with `json.loads` per line, run under the project venv's Python with `-I`. Rows follow §6.1: `captures[]`, else `file_references[]`, else one bodiless row. I counted raw lines, not de-duplicated rows. The scripts are `v8r_*.py` in this directory. Two of the three main passes took about 75 s and the third about 45 s.

## Verdicts

| ID | Verdict | Mine vs reviewer | Fix judgment |
|---|---|---|---|
| A1 | confirmed | 199,156 lines; 198,946 bodiless; 15 detail bodies, all exact. Also: only **18,140 meetings**, about 11 identical copies each | Direction right; key on a record content hash, not the line (below) |
| A2 | confirmed | 5,587 / 839 / 5,542 / 138, all exact | Data's fallback is close. Trace's "else `recovered_document`" mislabels 641 official substitutes. Better: fall back to `source_associations[0].basis` |
| A3 | partly | 4,286 lacking all three fields: exact. **"138 have no original URL anywhere" is wrong**: `source_associations[0].original_url` is on all 12,106 | Read `source_associations[0]`. Don't make `imported_at` nullable; take the receipt key's date |
| A4 | confirmed | 522,504 row entries (reviewer 522,501), 279,264 absolute (exact); 394,200 last segments are hex hashes | Data's rewrite is right |
| A5 | partly | 2,668,607 rows without `retrieved_at`: exact. "`_retrieved_at` on meeting lines" is **wrong** (16 of 199,156). "2,216,421 no time at all" is **overstated**: 1,925,085 | Data's fix recovers about 31 lines. Use an ordered time-key list (below) |
| A6 | confirmed | 554,784 lines without either URL; 1,418,037 body rows without a family | Right. Add a family precedence rule |
| A7 | **wrong** | All 79,112 `retry_later` lines also carry a publisher `Retry-After: 15` header; `delay_seconds` (30) is the fetcher's own backoff | No fix needed; the reviewer's fix would replace the publisher's value |
| A8 | confirmed | `url == recovered_url` on 11,950 (exact). Duplication applies to 11,076 lines whose URL is not the original (trace said 11,296, counting null as unequal). The circularity holds | Trace's fix is right |
| A9 | confirmed | `house/witness-xml` has 14,471 index rows (exact) and 3,571 bodies. The code's `HouseMeetingXML` holds meeting-documents only | Right. Also correct L379's "because it carries panels and witness documents" |
| A10 | partly | No formula: true. Old groups are names: true. **"No code computes one" is wrong**: `house_evidence.py` builds 1-based selectors and `owning_witness_selector` | Prefer document URLs on appearances, joined by `url_key` |
| A11 | confirmed | Text check | Storage's fix (exempt `is_completion`) beats trace's |
| A12 | confirmed | 0 of 15,707 index meeting IDs and 0 of 5,198 docs.house.gov folder IDs are non-digit; all 238,312 prefixed URLs are `PREFIX-congress-committee-…` filenames | Delete the sentence |
| A13 | confirmed (data); **fix wrong** | 1 of 34,576 (exact). Congress.gov writes `"jacketNumber":49104057` as an int (33 lines) | `list<string>` does not help. Match on the parsed package digits as an int |
| A14 | confirmed | 0 XML API responses | Fine |
| E2 | confirmed | 913–1,666 rows a Congress, 108th–119th (14,838 rows) | Right |
| E3 | confirmed | 20 at k=50, 18 at k=100, 11 at k=200; widest 57 B at 87,161 | Right |
| E6 | partly | Max 22,354: exact. The bodiless case is **one line with 3 entries** (`retained_as_receipts`), so 3 null-sha rows | Reword (below) |

## Details

### A1: inline Congress.gov meeting records (`v8r_meetings.py`, `v8r_a1*.py`)

**Storage.**
- All 199,156 lines are in the `congress/meetings` receipts: `undated/assemble-20260930.jsonl.gz` has 198,925, `undated/…-completion` 110, `2026-09-30/…` 120 and `2026-09-28/…` 1.
- The record is the line's `record` object, which is the Congress.gov meeting itself (`chamber`, `eventId`, `updateDate`, `hearingTranscript`, …, plus `_url` on 198,925 lines). On 15 lines it is wrapped as `record.meeting`.
- 210 lines carry `file_references` to 105 distinct bodies:
  - 90 are list-endpoint pages (`committee-meeting/{c}/{chamber}`, about 225 B);
  - 15 are detail responses (8 House, 7 Senate).
- `_retrieved_at` appears on 16 lines plus the 15 wrapped ones. No other meeting line has a fetch time.

**Identity.**
- 198,928 records name 18,140 `(chamber, eventId)` pairs.
- 18,123 of these have exactly one distinct content, so every copy is byte-identical in `record`; the copies differ only in `source_line`.
- 17 pairs have 2–3 versions: 14 differ in `updateDate`, and the rest differ in `_retrieved_at`.
- The records contain no floats. Hashing sorted-key canonical JSON, insertion-order compact JSON or the raw `record` substring gives the same version partition.

**So a SHA-256 of the compact JSON of `record` is a stable key.** It collapses the roughly 11× copies and separates real versions. A `(receipt_key, receipt_line)` locator (the data reviewer's fix) would mint about 199k rows for 18k meetings, and the current-record rule would then have to tie-break identical copies that have no fetch time.

**Better fix.** Rewrite §6.5 and §6.7:
- Source key: `record_sha`, which is `body_sha` for a body and SHA-256(compact JSON of `record`, or `record.meeting`) for an inline record.
- Rank Congress.gov records by `updateDate desc`, then fetch time, then key, because 99.98% have no fetch time.
- Invariant 5 should range over the producer's work list (bodies and inline records).

Jackets:
- Inline: 10,805 distinct (2,444 Senate).
- Bodies: `/v3/hearing/` response bodies cover 236 (1,489 lines), 158 of them also inline.

So "only inline" is true in substance.

**Could not see:** body bytes, so I could not confirm that the 90 list pages are empty.

### A2/A3: field presence over all 12,106 `retained_import` lines (`v8r_imports*.py`, `v8r_a2x.py`, `v8r_a3.py`)

All 12,106 lines are under `documents/`, with `mode` in `record` and a non-empty `captures[]`.

| Field | Lines |
|---|---|
| `record.url`, `requested_url`, `retrieved_at`, `publisher_requested` | 12,106 |
| `record.source_associations` (always exactly 1 entry) `.original_url` / `.basis` | 12,106 / 12,106 |
| `recovery_evidence.original_url` / `.imported_at` / `.match_basis` | 7,820 each (same lines) |
| `recovery_evidence.acquisition` (the 138 without it are `direct_official_package` 123 and `explicit_retained_download_wrapper` 15) | 11,968 |
| `acquisition.recovered_url`, `.kind` (format values: pdf 8,976, html 2,594, xml 370, doc 23, video 5), `.body_path`, `.sha256`, `.bytes` | 11,968 |
| `acquisition.original_url` | 6,381 |
| `acquisition.prior_access_category` (with `section_link`, `evidence_sha256`, `evidence_file`) | 5,587 |
| `acquisition.observed_capture_timestamp` | 6,132 |
| `acquisition.category` (format values: pdf, html_metadata_only, html_content, video_playlist, …) | 839 |
| `recovery_evidence.representation` (dict 7,820, string 722, absent 3,564), `.original_url` | 2,073 |

Agreement checks:
- Every line has exactly one distinct original URL across all four sources.
- `recovery_evidence.match_basis` equals `source_associations[0].basis` on all 7,820 lines that have both.
- `imported_at[:10]` equals the receipt key's date on all 7,820. The 4,286 lines without it are all under dated keys.

Basis crosstab:
- The 5,587 categorized lines are all `user_accepted_url_variant`; 5,154 of them (92%) are `recovered_document`.
- The 6,519 uncategorized lines are `user_accepted_url_variant` 3,520, `verified_archive_capture` 2,220, `official_document_identifier` 641, `direct_official_package` 123 and `explicit_retained_download_wrapper` 15.

**Fix.**
- §6.1: `original_url := source_associations[0].original_url` and `match_basis := source_associations[0].basis`. Both are complete on every line.
- `imported_at := recovery_evidence.imported_at`, else the receipt key's write date. This is complete, so §8.1 keeps it non-null.
- §7.8: `category := prior_access_category`, else `source_associations[0].basis`. The recovery-kind registry maps both vocabularies, and an unmapped value fails the build.
- Never read `acquisition.kind` or `acquisition.category`: they hold formats.
- Whether the 123 `direct_official_package` lines are recoveries at all is an owner decision.

### A4 (`v8r_scan.py`, `v8r_a4.py`)

| Entries | Count |
|---|---|
| `captures[]` entries with `original_path` (all inside `archive_members`) | 171,894 |
| `file_references[]` entries with `original_path` | 522,789 |
| — of which on rows (no `captures`) | 522,504 |
| — of which absolute | 279,264 (+285 on lines whose `file_references` are shadowed by `captures`) |
| Last segment a 64-hex hash | 394,200 |

None of the `file_references` entries is an archive member. The data reviewer's fix is right.

Separately, absolute `/Users/…` paths are still in the mirror, against §5.2's cleanup claim.

### A5 (`v8r_a5.py`)

Of the 2,668,607 rows without `retrieved_at`, the first fetch-time key each row carries:

| Key | Rows |
|---|---|
| `captured_at` (Senate captions) | 452,186 |
| `capture_date` (date only) | 40,278 |
| `observed_at` (13,844 Senate captions, 4,384 YouTube captions, …) | 20,119 |
| `started_at` | 11,641 |
| `parent_retrieved_at` | 10,598 |
| `checked_at` | 4,324 |
| `created_at` | 1,575 |
| `recorded_at` | 135 |
| Content dates only (198,912 meeting `date`/`updateDate`; YouTube upload dates) | 202,632 |
| No time-like key at all | 1,925,085 |

The time-less rows split by family as follows:
- Senate captions: 1,378,883, of which 910,719 are undated with no time.
- documents: 901,250, of which 880,058 have none.
- congress/meetings: 199,020.

L655 is therefore wrong. Caption rows are 52% of the time-less rows, and two-thirds of those carry no `captured_at`.

**Fix.** Make L259 an ordered key list in the versioned shape table:
- `retrieved_at`, `captured_at`, `observed_at`, `parent_retrieved_at`, `_retrieved_at`;
- then `capture_date`, at day precision;
- and say whether `started_at`/`checked_at` count as fetch times.

Rewrite L655 with the numbers above.

### A6 (`v8r_scan.py`, `v8r_a6.py`)

- 554,784 lines have neither URL field. Of these:
  - 215,750 have `_url`, `final_url`, `resolved_url` or `source_url`;
  - 339,086 have none (305,565 of those carry a body), mostly `{original_path}`-only bundle lines and MODS records.
- 1,418,037 body rows have no family on the entry or line.
- The entry family disagrees with the key's family on about 22k rows; for example, 8,661 `youtube/api` rows are labelled `senate/players`.

**Fix (data's, plus).** URLs nullable, with those fallbacks. Family precedence: the entry's, else the line's, else the receipt key's segment.

### A7 (`v8r_a7.py`)

All 79,112 lines with `retry_later.delay_seconds` are 503 / `retry_later` lines, and all carry `response_headers` `Retry-After: 15`. Every `delay_seconds` is 30, with reason `govinfo_zip_generation`. §6.1 L236 already reads the header. Reject the finding.

### A8

Recovered vs original URL:

| Case | Lines |
|---|---|
| Identical | 1,030 |
| Other host | 6,291 |
| Same host, different URL | 4,474 |
| web.archive.org | 311 |

The two-source-file case applies to the 11,076 non-identical lines when a recovery needs its own document. The circularity (L567 step 1 needs step 4's attachment) is real. Trace's fix is right: no source files from recovery rows; one bodiless row per distinct original link in step 1; delete rule 7.

### A9

Code:
- `HouseMeetingXML` (`committee-meeting`) exposes meeting-documents only.
- `HouseWitnessListXML` (`witness-list`) holds the panels, witnesses and witness-documents.
- `house_evidence.parse_retained_evidence(root, wlist)` takes them as separate bodies.

Raw:
- `house/witness-xml` has 11,178 receipt lines, 3,379 of which mention `WList`.
- A local `witness-list` body has `meeting-id="105543"`, 2 panels and 6 witnesses.

**Could not see:** a `committee-meeting` body, to prove it lists no witnesses.

**Fix.** As trace says. In addition:
- §7.11's `witness_keys` must take publisher links from the witness-list body;
- witness-list rows need their own completion or work-list rule.

### A10

**Fix.** Keep `group_path` inside `readings` for rendition groups only. Give `appearance_records` a `document_urls list<string>` (the witness's `doc-url`s) and join on `url_key`. If a path is kept, reuse `house_evidence.py`'s 1-based selector form; don't invent a 0-based one.

### A13 (`v8r_a13.py`)

`CHRG-118shrg049104057` is the only leading-zero jacket among 34,576 packages; jackets are 5–9 digits long.

**Fix.** Keep `list<int>`. In `transcripts`, parse `CHRG-{congress}{h|s|j}hrg{digits}` from each document's package ID and match on `(congress, chamber, int(digits))`. Never format an ID from the jacket.

### E3 (`v8r_e3.py`)

Distinct `context_url` per body (entry's, else the line's URL), over 1,011,635 bodies with a context.

**Could not see:** 286,843 body rows with no URL anywhere. At "≥ k" instead of "> k", k=50 gives 21.

### E6

Rewrite L226 as: "… on the row of a line without a body: 1,041,862 lines with no entries, and one line whose three file references were retained as receipts, one null-`sha256` row each". At §5.2 L134, add "`file_references[]` max 22,354".

## Scores (findings in my scope only)

| Reviewer | Score | Basis |
|---|---|---|
| data | **72** | A1, A4, A6, E2 and E3 are exact. A7 is wrong. A5 has a wrong `_retrieved_at` claim and an overstated no-time count. E6 is slightly off. The A1 line-key and A3 nullable fixes are weaker than available ones. |
| trace | **78** | A8, A9, A11, A12 and A14 are exact. A10's "no code" is wrong. "138 with no original URL" came from checking two of four shapes. A13's data is right but the fix fails. |
| storage | **90** | A11 (F9) is right, and its `is_completion` exemption is the correct fix. |
| reader | n/a | No finding in scope. |

**My confidence:** about 0.85. Counts come from full raw passes and match the reviewers' to the unit wherever they agree. The gaps are body bytes (A1 list pages, A9 `committee-meeting` XML), provenance decisions (A2), and the boundary sensitivity of E3.
