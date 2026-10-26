# Reconciliation: review round 7, 2026-10-26

The five review-6 reviewers re-read the four documents at `40ee51b2` in full: the spec reviewer, the systems professor and the editor (Fable), and the Iceberg/Parquet and bindings reviewers (Opus). Each wrote its own score before reading the lead editor's grade (`lead-opinion-review7.md`, 87), then judged that grade claim by claim. Three validation passes then re-measured every disputed or data-checkable finding. This file records the verdicts and what the pass of 2026-10-26 changed.

**Who found it:** Sp spec reviewer, Pr professor, Ed editor, Ic Iceberg/Parquet, Bi bindings. **Verdict:** ✓ confirmed by data, ⚙ confirmed in code or vendor docs, 📄 confirmed in the text, ◐ partly, ✗ refuted.

## Scores

| Reviewer | Score | Review 6 |
|---|---|---|
| Bindings | 88 | 85 |
| Spec reviewer | 85 | 74 |
| Professor | 84 | 77 |
| Editor | 83 | 78 |
| Iceberg/Parquet | 81 | 75 |
| **Mean** | **84** | 77 |
| Lead editor's own grade | 87 | — |

Every reviewer put the grade below the lead's 87. All agreed with the lead's raw-safety and executable-plan scores, its two nits, and its call to run S1 on real data; all disputed "internal consistency 9" and "grounded in data 9.5". The lead's "already checked" claim on multipart ETags was wrong (finding 6).

## How it was validated

All scripts and summary outputs are in `measurements/review7-validation-20261026/`.

- **raw/**: every receipt line read once (2,289 files, 2,596,054 lines), joined to the snapshot in UTC; 739 HEADs and 329 ranged GETs on both public hosts.
- **model/**: the model rules run by proxy on the snapshot, with each attempt's mode and completeness taken from raw; 700 HTML bodies fetched and classified by the committed short-page rule.
- **code/**: claims checked in the pinned crates (arrow-json 58.4.0, DataFusion 53.1, iceberg-catalog-rest 0.10.1), hyparquet 1.31.2, docspec-rs `d9c6719`, congressional-tech `d9730967` and Basin's docs; an offline arrow-json probe read two failing receipts.

## Root causes

1. **Older receipts were never measured end to end.** They are every line in the log today, yet the documents specified only the new line and left older shapes to "the ingest mapping". Findings 1–4 and 9 follow. *Fix:* M2 now reads all 2,289 receipts through the receipt reader and draft mapping, compared with the old index, before track C; DM §6.1 names where older shapes keep status, time and bodies.
2. **Fixtures covered only imagined shapes.** WARC envelopes, the GovInfo ZIP's manifests and the docs.house.gov 404 pairs surfaced only when the rules ran on real data. *Fix:* S1 runs over named real slices as well as fixtures, and gains a row for every sniffed format.
3. **A fix changed one place without re-checking its readers.** Review 6's dictionary fix contradicted A §11.1 and C3; the concision pass dropped three `list` derivations; the sniff fix made a copier miss permanent; the bindings adopted a reviewer's `locked_runtime` suggestion unchecked. *Fix:* this pass ends with a consumer check of every changed term across all four documents.

## Findings

| # | Finding | Who | Verdict | Evidence | Change |
|---|---|---|---|---|---|
| 1 | DataFusion's JSON reader fails a whole receipt on one type conflict | Ic | ⚙✓ | No switch in `JsonOptions` 53.1; 1,420 receipts hold a mixed-type path; `ignore_type_conflicts` reads all 778,684 lines of the largest failing receipt in 60 MB | A §13.1: conflicts become nulls and the raw line is kept; B C1: one `PartitionStream` per receipt with arrow-json, functions-json for nulled keys; P M2 measures it |
| 2 | `file_references` bodies missing from the `captures` grain | Ic | ✓ | 534,283 entries on 464,110 lines; the old index's 3,909,134 rows include them; DM's bodiless count already assumed them | DM §6.1 grain |
| 3 | D1's time count reads one field | Sp, Pr | ✓ | `captured_at` matches the HTTP Date on 99.99% of Senate caption lines; 501,487 of 522,448 untimed rows carry a fetch time, not 47,359 | P D1; DM §6.1 time mapping |
| 4 | Undated `assemble-*` status source | Pr | ✓ | 907,726 statuses come from `captures[].status_code` | DM §6.1 |
| 5 | WARC envelopes have no role | Pr | ✓ ◐ | 10,278 End of Term `.warc.gz`/`.arc.gz` bodies, each beside its stored payload; they poison 10,243 endpoints; the proposed `warc` arm never fires because the sniff sees a second gzip layer | DM §6.2 sniff reads the second layer; role `envelope`; invariant 8; S1 row |
| 6 | Multipart ETags on older bodies | Ic | ✓ | 61 of 588 bodies over 100 MiB, all from the 2026-10-01 bulk upload, identical on both hosts | DM §5.1 exception; invariant 2 and A §7.4 compare size and ETag with the record |
| 7 | "16,000 groups / 32,500 documents" | Pr | ◐ | 17,425 old groups pair a PDF with one docs.house.gov 404 body; the target joins about 34,000 GovInfo ZIPs (rule a) and about 700 same-stem groups (rule b) | DM §7.5; P E4 |
| 8 | GovInfo ZIP fixture and METS | Pr | ◐ | 33,980 of 34,196 hold five members; `dip.xml` root is `mets`; without METS in the registry the manifest joins the document | DM §7.1 row; S1 row |
| 9 | Writer identity bound to `locked_runtime` | Bi | ⚙ | It hashes seven package versions plus OS and machine; no commit | B receipt writer and importer; P B6 now says commit |
| 10 | Dictionary pages under ranged reads | Sp, Ic | ⚙ | hyparquet fetches the dictionary page on every ranged read; a byte cache keeps it | A §11.1; P C3 test |
| 11 | `list` lost three derivations | Sp | 📄 | — | DM §7.5 Columns |
| 12 | `context_url` undefined for top-level rows | Sp | 📄 | — | DM §5.2 |
| 13 | PDF copier miss becomes permanent | Sp | ✓ | Media type or old sniff finds 261,125 candidates; about 950 are HTML; 69 lack a PDF media type | P B13 checks `%PDF-`; DM §6.2 reads a miss whole |
| 14 | Materialization "in the pool" unbound | Ic, Bi | ⚙ | `DataFrame::cache()` collects outside the pool | A §9.1, §13.1; B C1 reserves batches or spills to scratch Parquet |
| 15 | No binding for drop with purge | Bi | ⚙ | `purge_table` exists; no job calls it | B C2, raw verifier |
| 16 | Credential seed includes bare `key` | Bi | ⚙✓ | 3,944,944 YouTube caption constants | B K1 |
| 17 | Plan steps without bindings | Bi | 📄 | — | B receipt writer patched before B0; B16 (was B17) after D2 |
| 18 | Budget overrun waits for a person | Pr, Sp | 📄 | — | A §12: publish starts the backfill |
| 19 | M1 has no decision rule | Ic | ⚙ | Basin compacts only files not yet compacted | P M1 rows check and ten-year scan rule; A §8.6 drops "a few GB a month" |
| 20 | Rules stated twice; B tables unreadable | Ed | 📄 | Ten B cells over 60 words | A §8.3, §8.5, §8.6, §9 cut to cites; B §3 as per-component lists (word bag unchanged) |
| 21 | Numbers without predicates | Sp, Pr | ✓ | 62% → three in four; 579 → 313 non-PDF; 3,558/11,044 → 3,690/11,792; 30% → 0.6%; 19,316 → about 25,500; 50 → 47; 27 now has its predicate | Each number rewritten in place |
| 22 | Cross-format edition ambiguity | Pr | ✗ | All 541 endpoints came from a file-shape test that never ran; 422 of 428 HTML bodies are error pages | No change |
| 23 | 23 GB ZIP walk | Pr | ✗ | No endpoint holds two real ZIP or PDF bodies once cut-off attempts drop out | DM §6.2 says none today |
| 24 | veterans.house.gov needs a second wrapper | Pr | ✗ | The second copy is a webharvest.gov recovery at the publisher's URL; it attaches, it does not merge by text; the page-version population is 2,250 pages saved twice in one fetch | P D2, E4 and the S1 row rewritten |
| 25 | Ceremony in P §3 | lead | ✗ | Every reviewer: the process rules are the owner's doctrine | Kept; only "Comments should be directed to the editor" and uncited references removed |

Minor findings folded in the same pass: the receipt reader's errors never print a line's text; `c.url` used throughout DM §7.3; the bodiless recovery row's source URL; conflict retry reuses written files; JSON link strings; table property spelling; stale `streamed-recovery` fix; reference and seed-citation repairs; `house_sites.py`'s lost calendar pages named. Rejected: dropping the PDF copier's HEAD on a 412 (older `.pdf` objects exist unverified).

**Owner decision, 2026-10-26:** files fetched from the End of Term archive are dated like any other fetch, so their archive capture time (2012–2017) is shown as "Captured <date>" (DM §6.1's time mapping already says so).

## Consumer check

An independent check diffed the pass against `40ee51b2` and followed every changed term through all four documents. It found three lost rules (the file-shape lists, "no journal", the 32 MB parent array), eight readers out of step (the gzip-PDF fixture, the source URL of a bodiless recovery row, materialization in A §13, dictionary pages in A §16 and P A1, P C1's test, the B0 patch scope, the copier's candidates, the engine ratchet), two list items the B §3 conversion split mid-thought, and an older contradiction (A §9.5 "link key" for body key). All were fixed. The official-substitute category names left DM §7.8 knowingly: they are registry contents (B K21).

## Result

| Document | Before | After |
|---|---|---|
| Architecture | 6,906 | 6,863 |
| Data model | 9,929 | 10,024 |
| Plan | 5,802 | 6,056 |
| Bindings | 5,198 | 5,488 |
| **Total** | **27,835** | **28,431** |

The data model grew with the older-shape mapping, the plan with M2's receipt input, the real-slice rule and the file-shape lists it now owns, and the bindings with per-component labels and the receipt reader. Cross-references: 315, none broken. Code references: 203, all resolve (three name DataFusion crate files).
