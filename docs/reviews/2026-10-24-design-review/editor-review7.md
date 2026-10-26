# Editor review 7: the four documents at commit `40ee51b2`

Read cold and in full on 2026-10-26 from `review-7/snapshot/docs/`. My independent view was written first (`editor-review7-own.md`); this file adds the review-6 status table and the verdict on the lead's opinion. Measurements: `ed7_measure.out` (words per section, sentence lengths, terms before definition, repeated 8-grams, boilerplate, section cites); cuts: `ed7_cuts.py`, which asserts every "before" exists verbatim in the snapshot.

Word counts (`wc -w`): **A 6,906** (was 7,004), **DM 9,929** (was 9,270), **P 5,802** (was 6,067), **B 5,198** (was 4,757); total 27,835 (was 27,098). DM and B grew with the 2026-10-25 decisions and with code facts; A and P shrank by removing restatement.

## 1. Score: 83 / 100

| Dimension | Score | Basis |
|---|---|---|
| One home per rule | 82 | All six round-6 must-fixes closed or nearly closed. Four rules were duplicated between A and DM *in this revision*; A §9 still restates three DM lists; two registries' contents are still in DM. |
| Concision | 78 | 470 words (1.7%) are restatement, history or ceremony that does no work (round 6: 2,371, 8.8%). The growth since round 6 is new rules, not padding. |
| Clarity | 86 | Every term used before its definition carries a forward cite (measured over 44 terms). `recovery row`, `catalog version`, `fingerprint candidate`, `attempt`, `main content`, `source URL` are now defined once. Prose averages 16–17 words a sentence, median 12–15. |
| Structure | 82 | Sections are right and in order. Readability fails inside tables: B §3 has ten cells over 60 words (longest 195), DM two (92, 83); one 72-word bullet in DM §6.1 and one 98-word bullet in P B0. |
| Change cost | 85 | A new publisher, receipt shape, release file or compressible format touches one home. A new registry entry still touches DM §7.3 (file shapes) and §7.8 (substitute categories) as well as the registry file. |

## 2. Findings

### Must-fix

**M1. Four rules duplicated between A and DM in this revision** (the habit that produced round 6's drift is live in new text).
- A §8.3 L300 / DM §6.2 L233: an operational failure writes no row. Home: DM (the `status` column's semantics). Cut A to a cite (A5).
- A §8.5 L310 / DM §6.4 L287, §6.5 L319: committee and meeting record sources. Home: DM; A keeps the purpose and the MUST (A6).
- A §8.6 L318 / DM §6 L179: "A lake table never changes schema in place" and the rebuild rule, in both. Home: DM; A keeps who drops and when (A7).
- DM §3 L61, §7.8 L612, §8.2 L665, A §9.5 L346: a recovery body is a real body only when a real fetch saved it. Home: the §3 definition; §7.8 keeps the count, §8.2 drops its sentence (D9, D10).

**M2. B §3.1–3.3 cannot be read as tables.** Ten cells exceed 60 words (L51 195, L56 158, L89 145, L61 144, L60 100, …). A five-column Markdown table renders each as one unbroken paragraph; the Fetcher cell holds eleven semicolon-separated work items. Rewrite each component as a short definition list (Component; Existing; Fit; Work as bullets; Suite). Saves no words; it is the one change that makes B usable by someone who did not write it.

### Should-fix

- **S1. A §9 still restates three DM lists** (§9.2 L330 the evidence roles; §9.3 L336 the engine paragraph; §9.4 L340 the date-source order). This section drifted in round 6. Cuts A8–A11 keep intent and cite DM §7.3, §7.5 and A §13.
- **S2. The engine-exclusion list appears three times, three wordings** (A §4.5 L142, §13 L487, §15.7 L505). §13 is the home (A1, A14).
- **S3. Registry contents still enumerated in DM** (§7.3 L453 both file-shape candidate lists; §7.8 L609 the six official-substitute categories). D4, D8; P E1 keeps the candidate counts because it owns that work.
- **S4. History in DM §7.7** (L598 "16,753 URLs waited under the old rules…"). The spec describes the target; P B17 holds the estimate (D6).
- **S5. P §5.3's rubric is A §9.2–9.3 in other words** (L147, 66 words). Fold the labeler's positive definition into A §9.2, which also makes §9.2 clearer, and cite it from P (A9 + P1; net −45).
- **S6. The six-recoveries owner-review item is in both P B7 (L197) and B §3.1 (L61).** Work belongs to P; B says "six doubtful recoveries go to owner review (plan B7)" (B2).
- **S7. Two bullets need splitting:** DM §6.1 older lines (L219, 72 words, three rules) and P B0 "The run" (L188, 98 words, three steps). D11, P9; format only.
- **S8. P B15 is a finding, not a task** (L205, 46 words). D1's comparison already restores the statuses it describes (P4).
- **S9. Uncited normative references.** `[[PARQUET]]` and `[[ICEBERG]]` are listed in A §17.1 and DM §11.1 and cited nowhere in either text. Cite once each (A §8.1 "Iceberg [[ICEBERG]] tables", A §10.1 or DM §8.1 "Parquet [[PARQUET]]") or drop them.
- **S10. The lead's two nits**, confirmed: A §6 diagram L183 says `captures` is "one row per body a receipt line references" while §8.2 L288 and DM §6.1 add the bodiless-line row → "one row per capture entry, or per bodiless line"; P §1 L29 "the capture schema carries `stored_sha256`" → "today's capture index carries `stored_sha256`" (the target drops it, DM §6.1). Zero words.

### Minor

A2 (Abstract repeats Status), A3/D1/P2 ("Comments should be directed to the editor", no editor named, three times), A4 (a measurement that sets no rule), A12 (§10.1 bullet repeats its table row), A13 ("There are no journals"), D2 (`body_key`/`stored_sha256` migration note), D3 (third statement of the §7.1 refusal), D5/D5b (archive-member bullet folds into the `locator` line), D7 ("No body hash"), P3 ("The safety net" repeats "The fields"), P5 (§6.3 done-when repeats C3's test), P6 (287,765 count is DM §6.2's), P7–P8 (A8, A9 restate A §10.1 and §8.5), B1 (`checked_put` in two rows), B3 (retryable-outcome list copied from DM §7.7), B4 ("Shims and legacy formats sit inside the rows above").

### On density, ceremony, definitions and the newcomer

- **Density** is not in the prose: A 333 sentences, mean 16.7 words, 8 over 40; DM 298, mean 16.6, 16 over 40; P 249, mean 16.2, 8 over 40; B 58, mean 13.1. It is in table cells (B ten over 60 words; DM §8.1 `detail` 92, §6.2 `links` 83) and in four bullets (DM §6.1 L219 72 words; P B0 L188 98; DM §7.7 L598 100 words in three sentences; A §7.1 L230 103 words in four). DM §7 is 3,984 words (40% of DM) and is dense by nature; its `:=` blocks are the clearest form for derivations and should stay.
- **Ceremony.** W3C front matter, conformance and references total 1,209 words (4.3%): A 400, DM 341, P 167, B 301. Nearly all of it does work (ToCs navigate; BCP 14 is required when MUST is used; B's Status explains the path abbreviations every row uses; P's Status sets reading expectations). What does none: "Comments should be directed to the editor" three times (21 words), A's Abstract restating the one-home convention that two Status sections also state (11), and the two uncited references in each spec. P §3's process rules are the owner's own doctrine (tickets, `wc -l` before and after deletions, project runners only) and brief agents; they are not ceremony.
- **Terms before definition.** Measured for 44 terms: six are used before the line that defines them (`good fetch` DM L300 vs L406; `link URL key` DM L400 vs L666; `wrapper` DM L346 vs L425; `raw check` A L244 vs L270; `pointer` A L41 vs L121; `canary` A L54 vs L127), and every such use carries a cite to the defining section or sits in the non-normative introduction or the conformance list. Not a finding.
- **Newcomer path.** A §1, §3 (31 terms) and the §6 diagram are a good on-ramp; DM §3's primitives close round 6's gap. The audience is implementers who know Parquet, Iceberg, DataFusion and R2 vocabulary; the documents rightly do not explain it.

## 3. Cut list (exact before → after; words saved)

Every "before" was matched verbatim against the snapshot by `ed7_cuts.py` (0 unmatched). Totals: **A 138, DM 131, P 166, B 35 = 470 words.** No rule, MUST or rule-bearing number is dropped; each entry says where the content keeps its home.

### A (138)

**A1 — §4.5 L142 (7).** Before: "Application policy (ID formulas, field names, grouping rules, registries, parsers) is passed in as SQL, data and specs and MUST NOT be compiled into the engine." After: "Application policy is passed in as SQL, data and specs and MUST NOT be compiled into the engine (§13)." The list lives in §13 L487.

**A2 — Abstract L7 (11).** Cut: "Every schema, derivation, order and registry is defined once, in [[DATA-MODEL]]." Status L11 and DM's Status say it.

**A3 — Status L11 (7).** Cut: "Comments should be directed to the editor." No editor is named.

**A4 — §7.1 L240 (9).** Cut: "Over half of body-bearing attempts find an existing body." A measurement that sets no rule.

**A5 — §8.3 L300 (10).** Before: "- **An operational failure writes no row**, so the input stays on the work list; only a deterministic rejection of the input is recorded as an error." After: "- **An operational failure writes no row** ([[DATA-MODEL]] §6.2), so the input stays on the work list." Rule kept in DM §6.2 L233.

**A6 — §8.5 L310 (35).** Before: "`committee_records` holds one row per committee in a Congress.gov committee API response, so pages show committee names instead of codes; `meeting_records` holds one row per meeting from the Congress.gov meeting JSON and its XML fallback for both chambers and from the House meeting inventories, so hearing pages show their title, date, type and committee ([[DATA-MODEL]] §6.4–6.5). Every response MUST come through the raw writer like any other fetch." After: "`committee_records` and `meeting_records` ([[DATA-MODEL]] §6.4–6.5) let pages show committee names instead of codes and a hearing's title, date, type and committee. Every response MUST come through the raw writer like any other fetch." Sources kept in DM §6.4 L287, §6.5 L319.

**A7 — §8.6 L318 (11).** Before: "**Schema changes rebuild.** A lake table never changes schema in place: a new schema is a new table version, built from raw and provenance in background batches, and the maintenance job drops the old one with purge when [[DATA-MODEL]] §6 allows." After: "**Schema changes rebuild.** A new schema is a new table version ([[DATA-MODEL]] §6), built in background batches; the maintenance job drops the old one with purge once [[DATA-MODEL]] §6 allows." Rule kept in DM §6 L179.

**A8 — §9.1 L326 (21).** Cut: "Public links do not depend on `document_id` (§10.1), so an ID that changes when a version joins a group costs nothing." §10.1 L371 says it.

**A9 — §9.2 L330 (−21; pairs with P1, net −45).** Before: "A document is one distinct content; its files are the real files with that content, in any format, judged from the sniffed format and the readings by what a page says rather than by site templates or length. Captions, playlists, API responses, metadata records, error pages, listing pages, download wrappers and damaged PDFs stay as evidence: they never enter a document, but they still drive `url_state`; listing pages supply link context, and a wrapper's file is queued for capture." After: "A document is one distinct content. A file is a real document when its main content is the document itself (testimony, a report, a transcript, a bill, a hearing record), not a list of links, a landing, download or error page, or metadata about a document; the rule reads this from the sniffed format and the readings, by what a page says rather than by site templates or length. Every other body stays as evidence ([[DATA-MODEL]] §7.3): it never enters a document, but it still drives `url_state`; listing pages supply link context, and a wrapper's file is queued for capture." The role list stays in DM §7.3 L414–430; the rubric gains its one home.

**A10 — §9.3 L336 (16).** Before: "Files connect through one node per body, fingerprint or rendition group, so a group of n files costs n edges, not n². Grouping runs in memory over dense integer IDs (a 32 MB parent array at 4M nodes; §13)." After: "Files connect through one node per body, fingerprint or rendition group, so a group of n files costs n edges, not n² (§13)." §5 L166 and §13 L481 hold the figures and the rule.

**A11 — §9.4 L340 (9).** Before: "The document date comes from the filename, else the contents, else the document's meeting, and is never a guess among several dates; the capture date is a real fetch's, never an import run's (§11.6)." After: "The document date is never a guess among several dates, and the capture date is a real fetch's, never an import run's ([[DATA-MODEL]] §7.5; §11.6)." Order kept in DM §7.5 L535.

**A12 — §10.1 L370 (14).** Before: "- **Documents only.** There are no per-copy pages; a document page shows where each copy was seen and which page linked it." After: "- **Documents only.** There are no per-copy pages." The table row L365 says the rest.

**A13 — §12 L467 (4).** Cut: "There are no journals." The sentence before it says runs resume by rerunning.

**A14 — §15.7 L505 (5).** Before: "no application identifiers (committee codes, family names, registry values) in the engine crate." After: "none of §13's exclusions in the engine crate."

### DM (131)

**D1 — Status L11 (7).** Cut: "Comments should be directed to the editor."

**D2 — §6.1 L218 (14).** Cut: "- No `body_key` (derivable from `sha256` and `stored_suffix`) and no `stored_sha256` (replaced by MD5)." A migration note; P D1 L240 records `stored_sha256` gone.

**D3 — §6.2 L254 (14).** Cut: "A registry change that adds candidates makes publish refuse until they are fingerprinted (§7.1)." §7.1 L337 is the MUST; A §12 L466 holds the budget rule.

**D4 — §7.3 L453 (19).** Before: "- `file_shaped(locator)` is true when a file-shape registry entry matches. The narrow list (`.pdf`, `.zip`, `.doc`, `.docx`, `.xml`, `/download/`, `download=1`, `file_id=`) marks 16,775 HTML bodies; a broader one (adding `/files/`, `/uploadedfiles/`, `/media/doc/` and more extensions) marks 44,047." After: "- `file_shaped(locator)` is true when a file-shape registry entry matches; the labeled sample fixes the list ([[IMPLEMENTATION-PLAN]] E1)." The counts stay in P E1 L256, which owns that work.

**D5 / D5b — §7.3 L455 and L447 (18 − 8 = 10).** Cut the bullet "- An archive member is judged by its own path (34,446 HTML members sit at successful ZIP URLs)." and carry the count on the formula line: "locator := the member path for an archive member (34,446 HTML members sit at successful ZIP URLs), else the URL".

**D6 — §7.7 L598 (21).** Cut: "16,753 URLs waited under the old rules, which never queued the files behind wrapper pages (*est.* 8,800 testimony and statement files)." History; P B17 L207 holds the estimate.

**D7 — §7.7 L599 (13).** Cut: "- No body hash: the 412 tells capture whether a body is new." Explains an absence; A §7.1 step 3 is the rule.

**D8 — §7.8 L609 (12).** Before: "or, for an official-substitute category (updated revision, introduced-bill counterpart, recorded votes, official report, complete statement, alternate amendment), the substitute it names." After: "or, for an official-substitute category, the substitute it names." The categories are the registry's (B §4 K21).

**D9 — §7.8 L612 (16).** Before: "- A recovery never makes a real file; its body is a real body only when a real fetch also saved it (3,558 of 11,044 recovery bodies today)." After: "- 3,558 of 11,044 recovery bodies today are also real bodies (§3)." Rule kept in §3 L61.

**D10 — §8.2 L665 (7).** Cut: "A recovery alone never makes a key." Implied by "every real body" and §3; inv 13 tests it.

**D11 (format, −2) — §6.1 L219.** Split the 72-word older-lines bullet into three: "sets `stored_suffix = '.gz'`;" / "takes each attempt's own status and completeness where the line records them, and otherwise sets `complete` true unless … compressed size);" / "sets `expansion = 'expanded'` on an archive line whose members were captured."

### P (166)

**P1 — §5.3 L147 (66; pairs with A9).** Before: "The labeling rubric: a file is a real document when its main content is the document itself (testimony, a report, a transcript, a bill, a hearing record), not a list of links to documents, a landing, download or error page, or metadata about a document. Two files are one document when they hold the same content: identical bytes, the same main text at one address, or one text in different formats." After: "The rubric is [[ARCHITECTURE]] §9.2–9.3."

**P2 — Status L11 (7).** Cut: "Comments should be directed to the editor."

**P3 — B0 L189 (11).** Cut: "- **The safety net:** the private 2026-10-24 backup keeps the originals." "The fields" L186 already says every receipt is in the backup before rewriting.

**P4 — B15 L205 (46).** Cut the item: "**The 2026-10-15 recovery run needs no correction.** All 5,587 lines of `receipts/documents/2026-10-15/download-filename-recovery-all-*` are `retained_import` recoveries with a synthetic HTTP 200 (5,154 recovered copies, 341 hearing-record excerpts, 92 official substitutes). The old capture index had flattened them into fetches. What remains is in D1 and E1." A finding, not work; D1's comparison restores those statuses.

**P5 — §6.3 L230 (9).** Before: "**Done when:** one CLI job runs the full export from Basin tables, byte-identical across threads, input orders and batch sizes and with a forced spill, on the smallest runner." After: "**Done when:** one CLI job runs the full export from Basin tables on the smallest runner and passes C3's test."

**P6 — D2 L244 (8).** Before: "(about 5 GB; 287,765 bodies the server labels HTML or XML)" After: "(about 5 GB)". DM §6.2 L250 holds the count.

**P7 — A8 L173 (13).** Before: "8. **Link context:** "where each copy was seen" names the page that linked it and the link's label." After: "8. **Link context** from `occurrences`."

**P8 — A9 L174 (9).** Before: "list every document for a hearing under its title, date, type and committee;" After: "list a hearing's documents;"

**P9 (format, −3) — B0 L188.** "The run" as three numbered steps (write with `If-Match` and `Content-MD5`; re-read and check the four equalities; record the result), then the rerun sentence.

### B (35)

**B1 — recovery importer L61 (6).** Cut "`checked_put` and its read-back (`packages/corpus_recovery/src/corpus_recovery/transfer.py:26-46,129-134`); and " — the body store row L56 lists it.

**B2 — recovery importer L61 (22).** Before: "where six recoveries that attach a 2-page Ways and Means excerpt to full 95–196-page docs.house.gov transcripts by "accepted URL variant" go to owner review; each one confirmed wrong gets a `rejected` decision." After: "with six doubtful recoveries sent to owner review (plan B7)." P B7 L197 holds the work item.

**B3 — fetcher L51 (−2).** Before: "retry only `retry_later`, `size_limit` and `request_failed`, not page classifications" After: "retry only the retryable outcomes of [[DATA-MODEL]] §7.7, not page classifications".

**B4 — §6 L180 (9).** Cut: "Shims and legacy formats sit inside the rows above."

## 4. Review-6 status

| # | Round-6 finding | Status | Where |
|---|---|---|---|
| M1 | A §9 restates DM §7 and has drifted | PARTLY | §9.7 drift fixed (L352 names no list); §9.2 L330, §9.3 L336, §9.4 L340 still restate (S1) |
| M2 | A §8.1 contradicts DM §6 on completion rows | RESOLVED | A L282 "an input that produced nothing still needs a row (DM §6)" |
| M3 | "import row" vs "import run" | RESOLVED | DM §3 L60 defines recovery row; L596, L604–612, L733–735 use it |
| M4 | `n_members` / `member_count` | RESOLVED | DM L585, L650 both `n_members` |
| M5 | "catalog" in three senses | RESOLVED | DM §3 L72 "catalog version"; A §3 L59 points to DM §3 |
| M6 | P restates the contracts it cites | RESOLVED | A-track L166–175, B2 L192, B9 L199, B13 L203, C0 L213, C table L217–226, D1–D2 L237–246 all cite; B0 is now the one home of the rewriter (B L66 cites it) |
| S1 | Body storage in A §7.1 and DM §5.1 | RESOLVED | A L232, L246 cite DM §5.1 |
| S2 | Older-line derivations split | RESOLVED | DM L131 holds no older-line text; L219 holds all three; A L242 no 64 MiB sentence |
| S3 | Registry contents enumerated in DM | PARTLY | §7.1 rows trimmed to "such as" (L343–366); §7.3 L453 and §7.8 L609 still enumerate (D4, D8) |
| S4 | Plan state inside DM | RESOLVED | L177 no caps note; L249 states the reason; L609 no plan note |
| S5 | A §16.2 is a plan step | RESOLVED | §16 has no 16.2 |
| S6 | A §15 restates DM §10, §10.2, §13 | PARTLY | Item 6 cites (L504); item 4 is now A's only home for the test list (acceptable); item 7 L505 still carries its own list (A14) |
| S7 | A §10.1 table duplicates DM §8.1 | PARTLY | Table kept with Purpose only (L360–368); "Detail reads" moved to §11.1 L423; "Binary keys" cut |
| S8 | A §13 item 3 restates §10.2 and DM §8.1 | RESOLVED | A L480 |
| S9 | Contract-suite sentence four times | PARTLY | P §2 L33 cites; A §4.8 L145, §6 L201 and B §1 L35 unchanged |
| S10 | Circular cites; duplicated credentials bullet | RESOLVED | A L415 no §12 cite; L465 cites §10.3.7; no "Separate credentials"; B L156; P L282 |
| S11 | Four names for the weekly job | RESOLVED | A §3 L130 "maintenance job"; "raw check" for the check; "Raw verifier" only as the §6 component |
| S12 | §11.6 re-derives `date_kind` | RESOLVED | A L447 |
| S13 | DM §7.5 Columns vs §8.1 | RESOLVED | DM L585 |
| S14 | "candidate" undefined | RESOLVED | DM §3 L63; A §3 L59 |
| S15 | Release ID in A, input identity in DM | RESOLVED | DM §8.3 L669–673; A L399 cites |
| S16 | P §4 order stated three times; "Other settled points" | RESOLVED | P L62–65 track order only; no settled-points paragraph |
| S17 | Labeled-sample sentence and rubric | PARTLY | P L147 cites A §15.2; the rubric remains (P1/A9) |
| S18 | B body-store and HTML/XML rows restate contracts | PARTLY | HTML/XML L75 cites DM §6.2; body store L56 cites A §7.1 but keeps the nine-writer list; `checked_put` in two rows (B1) |
| S19 | media-type MUST ×3; "Parsers record facts" ×2 | RESOLVED | DM L138 MUST once, L208 "§5.2"; A L296 no MUST; DM L226 no sentence |
| S20 | "1.39M, 7–18 min" ×4; sort order ×2 | RESOLVED | A L306, P L247 cut; DM L177 no sort-order sentence |
| S21 | A §8.3 Versions restates DM §7.1 | RESOLVED | A L302 |
| S22 | DM §7.2 strip-list bullet; §6.3 shared-SQL sentence | RESOLVED | No bullet; L282 "(§7.4)" |
| S23 | DM §8.1 pointer row carries behavior | RESOLVED | L659 "—" |
| S24 | Expiration policy in A, properties in DM | RESOLVED | A §8.6 L314 holds the catalog-level settings; DM L175 cites it |

Resolved 23, partly 7, open 0. The reconciliation (`reconciliation-review-6.md` §6) matches: 6.1 confirmed, 6.2 "partly fixed by the restore" (now done), 6.3–6.5 confirmed; its 1.9 made the recovery-kind fallback permanent as I suggested, and 2.4–2.7 defined the terms.

## 5. Verdict on the lead's opinion

| Lead's claim | Verdict | Evidence |
|---|---|---|
| Grade about 87/100 | PARTLY | The lead's grade averages six areas, two of which (raw-data safety 9.5, grounded in data 9.5) are outside the editorial lens and lift it. On the three editorial areas (consistency 9, simplicity 7, readability 7) the lead's own numbers average 7.7; my editorial score is 83. I do not dispute 87 as a whole-document grade; I dispute where it is lost. |
| Raw-data safety 9.5 | AGREE (not my lens) | Nothing in the text contradicts it; the create-only, 412, lock and backup rules are stated once each in A §7.1–7.4, DM §5.2 and P B0. |
| Grounded in data 9.5 | AGREE | Principle 9 (A L146); DM §7.3 L452 cites its 3,021-page sample; §6.1 L219 cites the 62% figure; §7.2 L399 the 34,095 ZIPs. The data-bearing sentences are what makes the few long ones long. |
| Internal consistency 9; "193 references, 0 problems" | AGREE | My own resolver checked 303 section cites across the four documents; all nine "unresolved" are RFC 3986 and INVENTORY sections, so 0 real problems. I checked ten rule pairs for contradiction (completion rows, concurrency group, 404 reload, Iceberg operations, record-role grain, retryable outcomes, recovery keys, saved-file order, maintenance settings, schema rebuild) and found none. The two nits are the only inconsistencies, both in non-normative text. |
| Executable plan 8.5; M1 and M2 open | AGREE (not my lens) | P §5.1–5.2 say so themselves; nothing editorial to add. |
| Simplicity 7 | PARTLY | The grouping block (DM §7.5 L489–541) is intricate, but each rule is stated once, cites a measurement, and now has an evaluation-order bullet (L543). I would give 7.5; nothing in it can be cut without losing a rule, so the lever is S1's executable model, not editing. |
| Readability and concision 7 | DISAGREE (too low, and mislocated) | Prose measures well: medians 12–15 words, 8–16 sentences over 40 words per document, every forward term cited. The readability failure the lead does not name is B §3: ten table cells over 60 words, the longest 195. Concision: 470 cuttable words (1.7%), down from 2,371. I score concision 78, clarity 86, structure 82. |
| Holds back 1: the grouping model is the hard part, checked only on fixtures | AGREE | Editorially it is as clear as prose allows; P §5.3 L104 already commits S1 to an executable model. |
| Holds back 2: ceremony in P §3 (tickets, `wc -l`, epics); corrected to "boilerplate that does not help a reader" | PARTLY | The uncorrected claim is wrong: P §3's rules are the owner's doctrine (project runners only, `wc -l` on deletions, tickets before commits) and are what agent briefs are cut from; they do work. The corrected claim is right and small: the boilerplate that helps no reader is 21 words of "Comments should be directed to the editor" (A, DM, P), A's Abstract sentence (11), and the uncited `[[PARQUET]]`/`[[ICEBERG]]` entries. The W3C frame (1,209 words, 4.3%) otherwise earns its place. |
| Holds back 3: density; DM §7.7 queue rule and A §7.1 fetching paragraph as examples; DM 9,900 words | PARTLY | The examples hold: DM §7.7 L598 is 100 words in three sentences (longest 42), A §7.1 L230 is 103 words in four (longest 39). But "many sentences" overstates the prose (10–13% of sentences exceed 30 words; 2–5% exceed 40) and understates the tables: B's 195-, 158-, 145- and 144-word cells and DM's 92- and 83-word cells are where a reader actually stalls, and the lead does not mention them. DM's size is new rules, not padding. |
| Nit: A §6 diagram omits the bodiless-line rows | AGREE | A L183 vs L288; fixed by S10 at zero words. |
| Nit: P §1 "capture schema carries `stored_sha256`" vs DM dropping it | AGREE | P L29 vs DM L218; "today's capture index" fixes it. |
| Raise 1: run S1's fixtures as an executable model, also on real data | AGREE (not my lens) | P §5.3 L104 already says the first half. |
| Raise 2: cut boilerplate and process rules; one more concision pass on DM §7 | PARTLY | Boilerplate yes (above). Process rules no. A DM §7 pass would now cut rules: my 131 DM words come mostly from history, migration notes and registry contents, not from §7's derivations. The concision pass that pays is B §3 (format) and the four new A/DM duplicates. |
| Raise 3: run M1 and M2, re-grade after | AGREE (not my lens) | — |
| Already checked: invariant 2's multipart clause holds | AGREE (not my lens) | Not disputed. |

**What the lead missed.** (1) B §3's table cells, the single largest readability cost (M2). (2) Four rules duplicated between A and DM in this very revision (M1), the pattern that caused round 6's drift. (3) A §9's three remaining restatements (S1). (4) Registry contents still in DM §7.3 and §7.8 (S3). (5) History in DM §7.7 and the six-recoveries work item in both P and B (S4, S6). (6) The uncited normative references (S9). (7) That the density sits in a few named bullets and cells rather than "many sentences", so the fix is splitting four bullets and re-laying B §3, not another prose pass.
