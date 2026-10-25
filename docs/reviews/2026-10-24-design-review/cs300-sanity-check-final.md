# CS 300 sanity check: design revision 7, data model revision 5, plan revision 4

Reviewer role: systems / data-intensive software engineering. Date: 2026-10-24. Checked at
`39e4662b`: `docs/engine-first-architecture.md` (**D7:line**), `docs/engine-first-data-model.md`
(**DM:line**), `docs/plans/simplification-plan-20261024.md` (**P4:line**), plus my three earlier
reviews. Not read: pipeline code, tickets, the other reviewers' files.

Spot-checks ran on the Oct 19 snapshot through the project venv (`measurements/cs300_sanity_checks.py`,
`measurements/cs300_sanity_layout.py` beside this review); the receipt-line link counts use the
four receipt files fetched publicly in earlier passes. This is a sanity pass, not a review:
everything below is either a contradiction, something a recent decision broke or left
undefined, or a number I tested.

## 1. Contradictions

| # | Where | What | Fix | Priority |
|---|---|---|---|---|
| C1 | D7:17–19 and D7:84–89 list five lake tables; D7:298 "registers the four lake tables"; P4:331 "Enable Basin compaction and snapshot expiration on all four tables" | Five tables exist (`captures`, `readings`, `filename_readings`, `page_links`, `committee_records`). As written, `committee_records` gets no maintenance and is not registered by the model job, which joins it (D7:415–419). | Say five everywhere; D5 enables maintenance on it. | must-fix |
| C2 | D7:474–475 "about 10 concurrent page reads, a few tens of KB"; D7:679 "11–43 KB"; DM:498 typed core + fold at 64 KB pages | The typed core as specified has **16 leaf columns** (recoveries 3, alternates 3, meeting_refs 2, plus 8 scalars) and the fold 2–3 more. Measured on 1.24M rows at 64 KB pages: the core alone is **≈414 KB per view** (`document_id` fsb(32) 39 MB and `saved_key` 38 MB are incompressible, so each costs a full 64 KB page per read); 123 KB at 16 KB pages; 350 KB without `document_id`. The 11–43 KB figure was the fold alone. | Restate the numbers; write the hash and key columns with 16 KB pages; move `document_id` (display-only) into the fold or drop it, since `link_key` is the public id. | must-fix (numbers); nice-to-have (layout) |
| C3 | D7:338 vs D7:342–344 and DM:351–355 | 16,775 file-shaped, 86,343 page-like and "about 2,100 under 16 KB" all come from the **narrow** eight-pattern list, but E1 "starts from the broader list" (44,047 file-shaped). With the broad list page-like is ≈59k, not 86k. | Label each number with its pattern list, or quote both. | nice-to-have |
| C4 | P4:42 (decision 10 "newest real file"), P4:45 (13 "a document type by sniffed format… not API metadata or playlist") vs P4:58 (26 "any content format") and P4:64 (32 "PDF first"); P4:40 (8 "every body's key") vs D7:464 ("every real file") | The decision table keeps superseded wordings beside their replacements with no marker. An E1 implementer reading row 13 writes the wrong rule. | Mark rows 8, 10 and 13 "amended by 26/27/32". | must-fix |
| C5 | DM:500 `ordinal` int16 | Today's largest document has **33,479** occurrences (one document above 32,767; five above 1,024). The new rule removes that error-page document, but the type is a latent overflow for nothing saved. | `ordinal` int32. | must-fix (one word) |
| C6 | D7:560 "Only two releases exist at a time" vs D7:545–550 "At least two… up to a week of daily releases" | Wording. | "At least two". | nice-to-have |
| C7 | D7:443 `url_state` ordered by `url`; DM:457–459 and DM:501 keyed by `requested_url` | Column name. | One name. | nice-to-have |
| C8 | D7:60, D7:320 "about 0.5M" vs D7:706 "about 560k rows readers didn't come for" | 1,241,157 − 453,751 captions − 98,205 records − 9,945 playlists − 1,112 API = **678k** before the untyped (101k, mostly PDF/HTML after the sniff) are classified and renditions merge (−16k to −20k): **0.6–0.68M**, not 0.5M. `list` at 0.5M measured 1.68 MB with meeting ids; at 0.65M ≈ 2.2 MB. | Say 0.6–0.7M; scale §6.2 sizes by 1.3. | nice-to-have |
| C9 | DM:431–434 meeting and package coverage | By the rule as written (per source file, union over members), the snapshot gives **116,901** documents with a docs.house.gov meeting URL (8,956 events), 163,476 with a Congress.gov one (12,041), 7,243 of 8,956 House IDs overlapping, and 108,753 documents / **72,374** govinfo packages. The data model's 45,761 / 6,551 / 142,997 / 11,634 / 4,715 of 6,550 / 141,694 / 36,943 come from some other basis (probably the saved file's URL only). | State the basis; the member-union numbers are the ones the rule produces. | nice-to-have |
| C10 | DM:321–322 "25,287 of 25,355 groups (99.7%) served identical bytes" | By latest body per URL, scheme/`www.` groups split 26,800 identical vs 4,757 differing (85%). The 99.7% needs its basis (any shared body across time?). | State the basis. | nice-to-have |

## 2. What the recent decisions broke or left undefined

**Efficiency.** Nothing superlinear and nothing O(history) was introduced. Two deliberate
O(N)-per-run items are worth naming so nobody "optimizes" them into the lake later: `url_key`
is recomputed over ≈1.2M URLs and every `page_links` row each run (regex work, seconds, and
rightly not stored, DM:306–307); `page_links` grows with page *re-fetches* × links, not with
documents (bounded by the recheck policy, which is still unstated, see U4). The sniff
(1.04M ranged GETs) and the 150-PDF text extraction are one-time and costed (D7:805–808).

**Determinism holes** (byte-identical exports are an acceptance test, P4:288–289):
- **H1 `linked_from`** (DM:508–510): "earliest `page_links` row … by `(retrieved_at, parent_url)`".
  About 1.0M captures have a null `retrieved_at` (DM:141), and one parent page often links the
  same URL twice with different labels. Ties pick an arbitrary label. Order by
  `(retrieved_at nulls last, parent_url, receipt_key, receipt_line, link_index)`. must-fix.
- **H2 `first_run`** (DM:370): "run_id of the earliest row" has the same null tie. Same fix.
- **H3** `alternates` (DM:394), `measure_keys`, `bioguide_ids`, `meeting_refs` (DM:428) are sets
  written as lists; state the order (format preference then `body_sha`; sorted strings; sorted
  `(chamber, event_id)`). nice-to-have but cheap.

**Rules E1 cannot write down from the text as it stands:**
- **U1 "real file" is per row, "same body" is per body** (DM:336–342 vs DM:377–378 and
  invariant 7). `real_files` is a set of capture rows, so an HTML body can be real at a
  page-shaped URL and not real at a file-shaped URL. `same_body` says "source files with the
  same body, where the body is a real file". Define `real_body := a body with at least one
  real_files row`, edges over source files whose own row is real, and let invariant 7 read
  "every real body". must-fix.
- **U2 `record_role` for JSON** (DM:332 "API-shaped JSON → api"): no definition. Name the
  families or JSON roots that count. must-fix.
- **U3 recovery-only documents** (D7:319–320, DM:389): a recovery attaches to a source file by
  `url_key(original_url)`. If the original URL was never fetched there is no capture row, no
  source file, no component, and invariant 12 reports it as orphaned, so "at least one
  recovery" can only list documents whose original link was also attempted. Either create a
  source file from the recovery's `original_url`, or say recoveries list only on attempted
  links. must-fix (one sentence either way).
- **U4 `url_state` recheck intervals** (DM:464–465 "the family's recheck interval"): no values.
  A small policy table (family → interval) belongs in the SQL. nice-to-have before F2.
- **U5 Senate committee codes** (D7:415–417 maps House codes to `hs…`): house-naming also
  reads Senate codes; say `ss` + code or "unmapped, reported". nice-to-have.
- **U6 generic stems and the page-shape list** (DM:384–386, DM:351–355): both say "and
  similar"; E1 already promises exact lists with sample tests, so this is a reminder that the
  lists are the deliverable, not the prose.

## 3. Spot-checks of numbers I had not measured

| Claim | Source | Measured | Verdict |
|---|---|---|---|
| 64,860 URLs (5.6%) differ only by scheme, `www.`, case or trailing slash | DM:296–297, D7:381 | 63,350 URLs (5.5%) in 31,673 groups | ✓ |
| 13,930 URLs (1.2%) carry a query string; `download` separates bodies in every group | DM:303–304 | 13,930 (1.2%) exact; 5,060 `download=` groups with the base URL present, bodies disjoint in all 5,060 (the 916 is presumably Senate hosts only) | ✓ |
| 16,156 same-directory same-stem groups across 32,547 documents | DM:402–403 | 19,955 groups across 39,919 documents with pdf/xml/htm/html/doc/docx/txt and a five-stem exclusion list | ✓ in magnitude; definition-dependent (C3/U6) |
| 265 identical real pages at 2–44 addresses | D7:372–373 | 264 pages, 2–44 addresses, 583 addresses | ✓ |
| 1,041,863 bodiless lines of 2,596,054 | DM:134 | 1,041,865 of 2,596,054 | ✓ |
| Delta-encoded `filename` 2.54 MB vs 3.22 MB with a dictionary on 1.13M sorted names (21% smaller) | DM:497 | 1,133,195 names: 2.45 MB vs 3.61 MB (32% smaller); at 500k: 1.82 vs 2.86 MB | ✓ (better than stated); hyparquet's README claims all encodings |
| `list` about 1.5 MB at 0.5M; `meeting_event_ids` about 1 MB | DM:497 | 1.68 MB at 0.5M rows with meeting ids (1.55 without); `meeting_event_ids` 0.12 MB at 0.5M, 0.25 MB at 1.24M | ✓ (ids cheaper than stated; total ≈2.2 MB at 0.65M, see C8) |
| Field coverage: congress 34.7%, meeting_date 16.0%, GPO 14.2%, measures 2–4%, members ≈3% | DM:210–213 | Over all 1.68M source files: 38.8%, 17.1%, 15.1%, 5.6%, 3.8%; ambiguous dates 0.3% of all files | ✓ within a few points (different base) |
| Receipt lines carry only document links, so `page_links` is 3–5M rows | D7:271 | Samples: 0 links per PDF line, 1 per meeting-XML line, 0.4 per Senate page line | plausible |

## 4. Is 8–16 weeks still realistic?

No at the low end. Since plan revision 3 the scope grew without any estimate moving:
`page_links` ingest and a second commit path (D1), `committee_records` plus the
`committees.py` rework (D5), typed keys in the filename-readings producer (D3), and in E1 the
`url_key` wrapper and strip lists with sample tests, `same_rendition` edges with two
mechanisms, meeting references, the committee mapping, the listing rule and a parity report
by cause over ≈600k differences; in A, alternates, link context, meeting filters, date
sorting and record link-outs (A5, A8, A9); in C3, per-column encodings and page row limits.
My additions: A +1–1.5 weeks, D +0.5–1, E +1.5–2.5, C3 +0.25–0.5, so **+3.3–5.5 weeks** overall
and **+2–3.5 on the critical path** (C→D→E→F). Realistic range: **11–20 weeks** for one
engineer, critical path 10.5–18. Two ways to keep 8–16: move decisions 31–36 (renditions,
meetings, dates, record keys, committee names) to a post-switch track G′ with their own
tickets, or accept 11–20 and say so. The measurement-first week and the parity-by-cause
design are unchanged and still the right shape.

## 5. Grades

**Architecture: A− (91), from A− (90).** Every item from the revision-5 pass is closed
(population, endpoint key, capture key, link context, recovery kinds, import day by run, hash
out of `url_state`, retention, costed one-time jobs). Held at A− by the per-view numbers in
§6.2/§12 being off by about 10× for the typed core (C2), the five-versus-four table count
(C1), and three rules E1 still cannot write down (U1–U3).

**Plan: B+ (87), from A− (88).** More complete and better instrumented (M2 harness, parity by
cause, every decision mapped to a step), but about 30% more scope at the same 8–16 weeks, and
a decision table that carries superseded rows. Fixing the estimate or deferring 31–36 restores
A−.

## 6. Fix before cutting tickets, ranked

1. **must-fix** — C4: mark decision rows 8, 10 and 13 as amended (one line each).
2. **must-fix** — U1: define `real_body` and the `same_body` edge per body, not per row; fix
   invariant 7's wording.
3. **must-fix** — C1: five lake tables in D7:298 and P4:331; `committee_records` gets
   maintenance.
4. **must-fix** — C2: correct the detail per-view numbers (≈120–400 KB with the typed core,
   not 11–43 KB) and set 16 KB pages for the key columns; move `document_id` to the fold.
5. **must-fix** — H1/H2: deterministic tie-breaks for `linked_from` and `first_run`.
6. **must-fix** — U3: say how a recovery whose link was never fetched is listed, or that it
   is not.
7. **must-fix** — U2: define "API-shaped JSON".
8. **must-fix** — C5: `ordinal` int32.
9. **must-fix** — §4: re-estimate (11–20 weeks) or defer decisions 31–36 past the switch.
10. **nice-to-have** — C3, C8, C9, C10: label the basis of each quoted count (pattern list,
    saved-file vs member URLs, latest vs any body) and raise "about 0.5M" to 0.6–0.7M with the
    sizes scaled.
11. **nice-to-have** — H3, U4, U5, C6, C7: list orders, recheck-interval table, Senate codes,
    "at least two", one name for the `url_state` key.
