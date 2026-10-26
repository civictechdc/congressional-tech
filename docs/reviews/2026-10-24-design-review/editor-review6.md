# Editor review: engine-first specifications (review 6)

Reviewed cold on 2026-10-25 against the frozen snapshot in `review-6/snapshot/docs/`:
A = `engine-first-architecture.md` (7,004 words), DM = `engine-first-data-model.md` (9,270), P = `plans/simplification-plan-20261024.md` (6,067), B = `plans/bindings-20261025.md` (4,757). Convention judged against: one home per rule (DM owns schemas, derivations and invariants; A owns behavior and cites DM; P only orders; B maps code), fixes folded in, not appended.

Word savings were counted by whitespace-splitting each quoted original and its replacement (`ed6_savings.py` in this folder). A negative number means the fix adds words to that document; the totals below are net.

## Verdict

**Sound and close.** The specifications are well structured, specific and mostly in one home each; most rules are stated once and cited elsewhere. The costs that remain come from three habits: A §9, A §10.1 and A §15 restate DM and other A sections (and A §9 has already drifted from DM); P restates the contracts it cites, against its own Status rule; and DM lists registry contents and plan state inside rules. Four term collisions would mislead an implementer. None of the findings changes behavior.

**Score: 78 / 100.**

| Dimension | Score | Why |
|---|---|---|
| One home per rule | 70 | Twelve rules live in two or more places; two have drifted (A §9.7 vs DM §7.2; `n_members` vs `member_count`). |
| Concision | 72 | 2,371 words (9%) are restatement, plan state in specs, or appended answers. |
| Clarity | 80 | Plain and active throughout; four term collisions (`import row`/`import run`, `catalog`, four names for the weekly job, undefined `candidate`). |
| Structure | 85 | Sections are in the right order; A §9, §10.1, §15, §16.2 and P §4 hold copies rather than content of their own. |
| Change cost | 78 | A new release file or compressible format touches two homes; a new registry entry touches the registry and DM. A new publisher or receipt shape touches one. |

Words saved: **A 895, DM 247, P 1,151, B 78; total 2,371.**

Counts: **6 must-fix, 24 should-fix, 10 minor.**

---

## Must-fix

### M1. A §9 restates DM §7 and has drifted (A lines 321–357)

A §9 is marked non-normative and says DM §7 "defines every rule", then restates the rules with their specifics: the evidence-role list (§9.2), the four edge kinds and the edition rule (§9.3), the saved-file order and date order (§9.4), the meeting, committee, kind and removal rules (§9.5), the review verdicts (§9.6) and the `url_key` steps (§9.7). Two have already drifted:

- §9.7 drops "scheme, `www.`, escape spelling, trackers, known page state"; DM §7.2 also drops the default port, the fragment and a trailing slash.
- §9.2's evidence list omits the body whose page reading failed (DM §7.3 `null` role).

§9.3's second paragraph (dense IDs, 32 MB parent array, node cap) is engine behavior stated again in §13 item 4 and §5.

**Rewrite:** keep one intent paragraph per subsection with no restated list, order or threshold, each citing its DM home. For example:

> ### 9.7 URL Normalization
> Link joins use `url_key` ([[DATA-MODEL]] §7.2); identity keeps the exact URL.

> ### 9.3 Grouping
> Source files connect by shared body, shared text at one address, publisher grouping and reviewer merge; connections chain ([[DATA-MODEL]] §7.5). A new edition is a new document, so mirrors cannot merge editions transitively.

Full replacement text for §9.2–9.7 is in `ed6_savings.py` (entry "M1"). **Saves 359 words.**

### M2. A §8.1 contradicts DM §6 on completion rows (A line 278)

A: "Every producer ... writes a completion row ... for an input that produced nothing." DM §6: only `committee_records` and `meeting_records` write completion rows; "`readings` and `filename_readings` need none: they write one row per input with a status." A's rule is wrong as written.

**Rewrite:** "Every producer finds its work by an anti-join of its inputs against its rows, and records, in the same commit, each input that produced nothing ([[DATA-MODEL]] §6)." **Saves 4 words.**

### M3. "import row" and "import run" mean opposite things (DM §6.1, §7.4, §7.7, §7.8, inv 13)

"Import run" = a bulk run of real fetches (`mode = fetch`, A §3). "Import row/line" = a recovery import (`mode = retained_import`, DM §6.1 "Import rows only"). They differ by one word. DM §7.7 "Import rows MUST NOT appear" sits two lines after "The latest `mode = fetch` attempt wins", which includes import-run rows; a reader who takes "import rows" as import-run rows reads a contradiction, and `url_state` would lose 2.7M attempts.

**Rewrite:** replace "import row" / "import line" with "recovery row" / "recovery line" at DM lines 181, 191, 450, 456, 493, 565, 573–577 and 710 (13 occurrences). Keep "import run". **Saves 0 words.**

### M4. One field, two names: `n_members` and `member_count` (DM §7.5 line 554, §8.1 line 624)

The `documents` relation has `n_members`; the `detail` fold has `member_count`. Nothing says they are the same column.

**Rewrite:** one name; `n_members` matches the relation. Fold the fix into S13 below. **Saves 0 words.**

### M5. "catalog" has three meanings, two in one principle (A §4 item 3, §8.4, §16.1; DM §6.3)

A §4.3: "every filename is read once per catalog version. Platform primitives (... catalog commits) ..." The first "catalog" is the filename parser bundle (`catalog_version`, DM §6.3); the second is Basin Catalog; elsewhere "the pinned catalog pair" and "1.24M catalog rows" are the old derived catalog (P). A new reader cannot tell which commits §4.3 means.

**Rewrite:** add to A §3:

> **catalog version**
> : The filename parser's version ([[DATA-MODEL]] §6.3). Basin Catalog is always named in full.

and in P, call the old artifact "the pinned old catalog" on first use. Renaming `catalog_version` to `naming_version` would remove the collision at the source; that is a schema decision for the owner. **Costs 16 words.**

### M6. P restates the contracts it cites (P §6.1 A1–A10, §6.2 B0, B2, B9, B13, §6.3 C0 and the C table, §6.4 D1–D2)

P's Status says: "It cites the specifications' contracts rather than restating them." The track sections do both. Examples:

- **A1** (line 165) restates A §11.1, §11.3, §11.4 ("decoded column by column", "No DOM dependency", "Accepts the current and previous `schema_version`", the 404 reload). A2, A5, A6, A10 restate A §10.1, §11.5, §11.6 and DM §7.9.
- **B0** (lines 184–188): "The rule is the one [[DATA-MODEL]] §5.2 states:" followed by the rule; "The tool" and "The run" restate B §3.1's receipt-rewriter row and DM §5.3's verification fields.
- **B2** (line 191): "to [[ARCHITECTURE]] §7.1–7.2 and [[DATA-MODEL]] §5.2, proven by their contract suites:" followed by 50 words of §7.1–7.2.
- **B13** (line 202) duplicates B §3.1's PDF-copier work cell and DM §5.3.
- **C0** (line 211) is B §3.3's C0 row verbatim; the C table's "Capability" column is A §13 rewritten, and C5 adds "single create-only PUTs with no multipart", which A §13 item 5 does not say (that rule is §7.1's) — drift already.
- **D1–D2** (lines 234–244) restate A §8.2 and DM §6.1–6.2 (older-row derivations, sniff reads, the fingerprint estimate).

Every restatement is a second home that will drift when the spec changes. **Rewrite:** each task keeps its citation, its plan-only facts (library choice, fixture, measurement, order, size) and its done-when; the rule text goes. Replacement text for each is in `ed6_savings.py` ("M6" entries). For A-track:

> 1. **Reader** ([[ARCHITECTURE]] §11.1–11.4): hyparquet's `useOffsetIndex` for `detail`, with each row group's offset index cached per session, and `usePageIndex` for `links`; shards.
> 2. **Links** resolve through `links` ([[ARCHITECTURE]] §10.1, §11.5).
> 3. **Canary** ([[ARCHITECTURE]] §10.3.5), run by the publish job.
> ...

**Saves 794 words** (B0 141, B2 49, B9 20, B13 60, A-track 198, C 163, D 163).

---

## Should-fix

### S1. Body storage rule in A §7.1 and DM §5.1 (A lines 226–228, 242)

"Stored bytes" (the compressible-type list), "Two digests" and "Older bodies" restate DM §5.1's Key, Stored bytes, HTTP metadata and Custom metadata rows. A new compressible format touches both.

**Rewrite A §7.1:** "**Stored bytes** follow [[DATA-MODEL]] §5.1, so an HTTP client that honors `Content-Encoding` receives the original bytes. The original's SHA-256 is the identity; the stored bytes' MD5, which R2 verifies on upload and returns as the ETag, is the integrity check." and "**Older bodies** keep their `.gz` form; older gzip PDFs gain a `.pdf` copy ([[DATA-MODEL]] §5.1)." Also point A §7.1's `sha` definition at DM §5.2, where `sha256` is defined, not §5.1. **Saves 49 words.**

### S2. Older-line derivations split between DM §5.2 and §6.1, with a third copy in A §7.1 (DM lines 96, 197; A line 238)

`complete` for older lines is derived in §5.2's cell ("false for the bodies older runs cut off at 64 MiB"), `expansion` in §6.1's "Older lines" bullet, `stored_suffix` in §6.1's column note; A §7.1 adds "This includes the bodies older runs cut off at 64 MiB."

**Rewrite:** §6.1 "Older lines" bullet holds all three: "the ingest mapping sets `stored_suffix = '.gz'`, derives `complete` (false for the bodies older runs cut off at 64 MiB), and sets `expansion = 'expanded'` on an archive line whose members were captured." §5.2's cell ends "Older lines carry none (§6.1)." Cut A's sentence. **Saves 11 words net; one home.**

### S3. Registry contents enumerated inside DM rules (DM §7.1 rows, §7.3 bullet 2, §7.8 table)

The owner's change-cost question "a new registry entry: one place or many?" answers "two" today. §7.1 lists the filename parameters in order, the error words, the strip-list samples; §7.3 lists both file-shape candidate lists; §7.8 maps every recovery category to a kind. The registry file is the home (§7.1: "one file beside the model SQL ... each entry with a real sample a test checks"); the spec copies will drift.

**Rewrite:** describe the kind of entry and keep at most one "such as". Filename parameters: "Query parameters that name a file, in priority order". Error words: "Error words for a title or heading, and body markers of challenge and soft-error pages". §7.3: "`file_shaped(locator)` is true when a file-shape registry entry matches; the registry's two candidate lists mark 16,775 and 44,047 HTML bodies ([[IMPLEMENTATION-PLAN]] E1)." §7.8: replace the table with "The registry maps each category to one of three kinds: recovered copy, hearing-record excerpt, or the official substitute the category names." (The three kinds are a closed set the recovery order sorts on, so they stay.) **Saves 53 words.**

### S4. Plan state inside DM (DM lines 155, 227, 578)

- §6 Writer settings: "*(Note: these sizes assume the engine's remote write caps go; [[IMPLEMENTATION-PLAN]] M1 decides, and this note goes with it.)*" — P M1 item 3 already says it changes DM §6 if the measurement says so.
- §6.2 sniff: "It runs after the PDF copies exist." and "(in practice, every older body)" — P D2 orders it.
- §7.8: "a fallback that goes once every import carries a category ([[IMPLEMENTATION-PLAN]] B7)" — doubtful as well as misplaced: older receipts are immutable under the lock, so an import with no category keeps needing the decision's kind.

**Rewrite:** cut the three notes; §7.8 reads "an import with no category takes its decision's `kind`." **Saves 43 words.**

### S5. A §16.2 is a plan step (A lines 535–539)

"Validate Before Building" names what P §5 measures and when. A describes the target; P orders. **Cut.** **Saves 51 words.**

### S6. A §15 restates DM §10, §10.2, §10.3.5 and §13 (A lines 506–512)

Item 1 already delegates to DM §10; items 4, 6 and 7 then restate the determinism conditions (§10.2), the 404 rule (§11.3, inv 21) and the engine exclusions (§13, with a third list that differs from §4.5 and §13).

**Rewrite:**

> 1. **Invariants:** [[DATA-MODEL]] §10, as tests over the raw log, the lake, the model's relations and each release.
> 2. **Rule accuracy:** (unchanged)
> 3. **Registry samples:** (unchanged)
> 4. **Determinism** (§10.2) and the **canary** (§10.3.5) on every candidate.
> 5. **Contract:** (unchanged)
> 6. **Ratchets:** tests assert §13's exclusions and principle 8's adapter injection.

**Saves 71 words.**

### S7. A §10.1's file table is a second home for DM §8.1, and read behavior sits in §10 (A lines 363–379)

The table lists the release files with a "How it is read" column; DM §8.1 lists them with writer profiles; A §11.1 says how they are read. A new release file touches three places. The "Detail reads" and "Binary keys" bullets are §11.1 and DM §4 again.

**Rewrite:** §10.1 opens "The model's job writes the release files of [[DATA-MODEL]] §8.1, linked by the list row number." and keeps the Documents-only, Links-point-at-a-file, No-ID and Growth bullets. §11.1's sentence becomes "Details and ranges are HTTP Range reads of single pages through the Parquet offset index, fetched once per row group per session, so a detail view is one round trip; link lookups also use the column index." **Saves 175 words net.**

### S8. A §13 item 3 restates §10.2 and DM §8.1 (A line 487)

"fixed row counts per row group; unique sort keys" appear in §10.2, §13.3 and DM §8.1. **Rewrite:** "**Deterministic multi-file export** to §10.2 and the writer settings of [[DATA-MODEL]] §8.1, with SHA-256 and MD5 computed while writing and row-range shards." **Saves 19 words.**

### S9. The contract-suite sentence appears four times (A §4.8, A §6, P §2, B §1)

"Any implementation that passes the suite may stand behind the component" is in A §4 item 8, A §6 (the home, beside the component table), P §2 and B §1. **Rewrite:** A §4.8 ends "may stand behind it (§6)."; P §2 "Contracts first" becomes "A component's contract suite ([[ARCHITECTURE]] §6) is written before any code is bound to it."; B §1 keeps its one clause. **Saves 37 words.**

### S10. Circular citations and a duplicated bullet (A §10.3.7 ↔ §12; P F4 ↔ B §6; A §12 vs §14)

- A §10.3.7 cites §12 for the concurrency group; §12 cites §10.3.7. Home: §10.3.7. §12's bullet becomes "Only publish and maintenance ingest captures, and they never overlap (§10.3.7)."
- B §6 intro ("one PR per group, measured again at cut (plan F4)") and P F4 say the same with mutual cites; B §6 becomes "Deleted at the switch (plan F4)." P F4 loses "The engine cuts apply only to code no consumer uses after the switch", which B §6 already says.
- A §12 "Separate credentials" duplicates §14's second bullet. Cut from §12.

**Saves 51 words** (A 30, B 8, P 13).

### S11. Four names for one job (A §7.4, §8.7, §10.3.7, §12, §16.1; P B9)

"weekly check" (6 times), "weekly maintenance job", "weekly job", "maintenance" (the §12 diagram), and the component "Raw verifier" (A §6). **Rewrite:** "maintenance job" for the job everywhere, "raw verifier" only for the component in §6 and B. **Saves 0 words.**

### S12. A §11.6 re-derives `date_kind` in words (A line 454)

DM §8.1's `date_kind` already encodes the three states; §11.6 restates the derivation ("for a real fetch", "when only `in_archive_since` is known", "otherwise"). A fourth kind would need both edited in lockstep by inference.

**Rewrite:** "The reader MUST label a capture date by `date_kind` ([[DATA-MODEL]] §8.1): `captured`, "Captured <date>"; `import_day`, "In our archive since <date> (original capture date not recorded)"; `unknown`, "Capture date not recorded"." **Saves 4 words.**

### S13. DM §7.5 "Columns" duplicates §8.1's types and is incomplete (DM line 554)

The Columns line restates `detail`'s typed core with types, omits `alternates`, `meeting_keys`, `committee_name`, `document_kind` and `source_url` that §8.1 reads from it, and names `n_members` where §8.1 says `member_count` (M4). **Rewrite:** "**Columns:** the names derived above, typed as `detail` reads them (§8.1), plus `document_id` fsb(32), `list_row` int32, `hidden` bool, `review_note` string nullable, `review_decided_at` date32 nullable and `n_members` int32." and change `member_count` to `n_members` in §8.1. **Saves 36 words.**

### S14. "candidate" is used 17 times and defined nowhere (A §8.3; DM §6.2, §7.5; P)

DM §6.2 defines it only by implication ("reads the other candidates: the bodies at endpoints with two or more distinct real bodies"), and the page parsers fingerprint every page, so whether an uncontested HTML body is a candidate is unclear. **Rewrite DM §6.2:** "A body is a **fingerprint candidate** when it sits at an endpoint with two or more distinct real bodies (`real_files`, §7.3). The page parsers fingerprint every page; **`fingerprint`** reads the candidates of other formats." Add the term to A §3 with a cite. **Costs 16 words.**

### S15. The release-ID formula is in A, the input identity in DM (A §10.3.3; DM §8.3, inv 20)

Both are derivations; DM owns derivations and inv 20 restates the formula. **Rewrite:** DM §8.3 becomes "Identities" and gains "The **release ID** is the SHA-256 of the file list (name, SHA-256, size, rows) and the schema version."; A §10.3.3 reads "The release ID ([[DATA-MODEL]] §8.3) is computed after export and before upload." **Saves 6 words net; one home.**

### S16. P §4 states the B-track order three times, and "Other settled points" duplicates tasks (P lines 60, 64–70, 75)

The numbered list, the table's "Depends on" column and §6.2's task parentheticals (B10 "after B13", B13 "after B1 and B3") all carry the within-track order. "Other settled points" (line 60) are tasks B4, B6 and B12 restated. **Rewrite:** the list keeps track order only:

> 1. The bucket lock on `bodies/` and `provenance/` (B1), at once; the cut-off re-fetch (B14) beside it.
> 2. M1, M2 and S1; S2 beside track C.
> 3. F0 and the hand-built fixture; C0; tracks A and B.
> 4. Track C, then D, then E, then F.

The table keeps dependencies; tasks keep their own "after" notes. Cut "Other settled points". **Saves 99 words.**

### S17. The labeled-sample sentence is A §15 item 2 verbatim, and the rubric is a second definition of "document" (P line 146)

"It measures how often the file-shape, error-sign, listing-page, placeholder and rendition rules wrongly include, exclude or join a file" is copied from A §15.2; the rubric ("a file is a real document when ... Two files are one document when ...") re-defines A §9.2–9.3 in other words, so a rule change can leave labelers on the old rule. **Rewrite:** cite A §15, item 2 for what the sample measures and A §9.2–9.3 for the rubric; keep the strata and what the sample sets. Replacement in `ed6_savings.py` ("S17"). **Saves 91 words.**

### S18. B work cells that restate the contract instead of naming the gap (B §3.1 Body store; §3.2 Parsers: HTML and XML)

B's Status: "Each work cell names the code fact that breaks a cited clause; the rule itself stays in the specifications." The body store row restates A §7.1's write steps and lists nine writers that §6 lists again (`checked_put` appears three times in B). The HTML/XML row lists DM §6.2's columns, so a new reading column touches DM and B. **Rewrite:** body store: "the write steps of [[ARCHITECTURE]] §7.1 (today: `Content-Type: application/gzip`, `ca/retention/r2.py:121-123`). Not bound: ... The nine other writers (§6) are routed through the store, then deleted;" and move the writer list into §6's raw-index row. HTML/XML: "A new lxml pass (*est.* 150–250 lines) that records the columns of [[DATA-MODEL]] §6.2, none of which today's code records, with no resolution, dedupe or classification." **Saves 62 words.**

### S19. Three small rules stated twice (A §8.3; DM §5.2, §6.1, §6.2)

- "media type MUST NOT classify": DM §5.2 (home), DM §6.1 column note, A §8.3. Keep the MUST once; §6.1 note becomes "§5.2."; cut A's sentence.
- "Parsers record facts; the model classifies them." is verbatim in A §8.3 and DM §6.2. Cut from DM.

**Saves 20 words.**

### S20. Measurements repeated across documents (A §8.4, §16.1; DM §6.3; P D3; A §8.1; DM §6)

"1.39M pairs, 7–18 minutes" is in four places; keep DM §6.3 (size) and A §16.1 (cost). "Nothing depends on sort order" is in A §8.1 and DM §6; keep A (behavior), cut DM's. **Saves 16 words.**

### S21. A §8.3 "Versions" restates DM §7.1 (A line 297)

**Rewrite:** "**Versions** follow [[DATA-MODEL]] §7.1." **Saves 28 words.**

### S22. DM §7.2 and §6.3 say the same thing twice within a section (DM lines 380, 260)

§7.2's bullet "Only trackers and named page-state parameters are stripped; other parameters ... almost always select a different file" restates the formula's "drop the strip-list parameters; sort the remaining parameters and keep them all" and the strip-list registry row; cut it (its rationale fits the registry row if wanted). §6.3's "The producer computes the effective filename with the model's own SQL (§7.4), so the work list depends on no model decision" restates §7.4's "by one SQL definition that the filename producer (§6.3) and the model share"; reduce to "by §7.4". **Saves 34 words.**

### S23. DM §8.1 pointer row carries behavior in the writer-settings cell (DM line 633)

"`no-store`; written only by the flip, with `If-Match`" is A §10.3.6. **Rewrite:** "—". **Saves 7 words.**

### S24. Expiration policy lives in A, the other table properties in DM (A §8.7; DM §6)

"older than 30 days, keeping the last 5" is a table setting stated only in A, while the 128 MB target is in both. **Rewrite:** DM §6 Table properties gains "snapshot expiration after 30 days, keeping the last 5"; A §8.7 reads "Basin Catalog compacts each table and expires snapshots as the [[DATA-MODEL]] §6 table properties say." **Saves 2 words net; one home.**

---

## Minor

### m1. Appended clauses that answer one question (fold or cut)

Each reads as bolted on after a review question; none carries a rule the surrounding text lacks.

- A §7.4 "(about 1,300 list requests once the `.pdf` copies exist)" — §16.1 holds it. 9 words.
- A §7.1 "Over half of body-bearing attempts find an existing body." — a measurement; §5 or cut. 9.
- A §8.7 "which holds the delete credential," — §14 says it. 5.
- A §12 "There are no journals." — the previous clause already says runs resume by rerunning. 4.
- A §11.2 "There is no per-view byte budget." — negative decision record; "the heap budget is the only size target" if kept. 6.
- A §10.1 "At that size `list` reaches 40 MB; then it is sharded by facet, or search moves to DuckDB-WASM or a server." — speculative; P §7's freeze forbids this work until measured. 21.
- DM §5.2 "This is the one definition of a complete fetch." 9.
- DM §6.1 "No `body_key` ... and no `stored_sha256` (replaced by MD5)." — migration note; P D1 says it. 14.
- DM §7.7 "No body hash: the 412 tells capture whether a body is new." 13.
- DM §6.6 "Fingerprint candidates do not wait for it." 7.
- DM §7.5 "A reviewer's merge still joins any two documents." — §7.9's rule. 8.
- DM §7.8 "One import row therefore yields exactly one recovery." — the PK and inv 13 say it. 8.
- P B1 "Creates stay allowed under it, so B13 is unaffected. The single most protective step." 14.
- P §6.5 "A full Python rebuild of the old catalog is not needed: the pinned catalog pair is the oracle." — fold "the oracle" into E4. 18.

**Saves 145 words.**

### m2. P B15 is a finding, not a task (P line 204)

"The 2026-10-15 recovery run needs no correction ..." records that nothing is owed. Move the one fact that matters ("the old capture index had flattened them into fetches") to B §8 as a non-defect, or cut. **Saves 46 words.**

### m3. P B3 defines the refusal matrix from the specs (P line 192)

Its content is A §7.1 step 3 and DM §5.2's MUST NOT. **Rewrite:** "Write the refusal matrix first, as the body store's contract test ([[ARCHITECTURE]] §7.1, [[DATA-MODEL]] §5.2): a refused write makes no I/O." **Saves 18 words.**

### m4. B §4 K14 restates the `intact` rule (B line 123)

"(`%%EOF` in the last 8 KB, else a bounded reader)" is DM §5.2; B maps code. Cut the parenthetical. The 8 KB also appears in DM §6.2's sniff bullet; "the `intact` check of §5.2 on its `.pdf` copy's tail" would leave one home. **Saves 10 words.**

### m5. B §3.3 C2 hard-codes "at most three retries" (B line 88)

The count is A §8.1's. "the conflict loop of [[ARCHITECTURE]] §8.1". **Costs 2 words.**

### m6. P D2 repeats DM §6.2's fingerprint estimate (P line 243)

Cut "(*est.* 300 to 1,800 bodies: up to 13 GB of PDF text, ZIPs from their members)". **Saves 16 words.**

### m7. P §7 restates DM §4's fold decision (P line 295)

"House-naming metadata stays typed facets plus the fold regardless." is DM §4. **Saves 9 words.**

### m8. DM §7.3 bullet restates `locator` (DM line 430)

"An archive member is judged by its own path (about 34,000 HTML members sit at successful ZIP URLs)." — the formula says it; keep the number in §5 Scale if wanted. **Saves 19 words.**

### m9. A §8.5 and §8.6 both say "fetched through the raw writer"

Merge into one subsection "`committee_records` and `meeting_records`" with the sentence once. **Saves 13 words.**

### m10. Invariants that copy a derivation (DM §10 items 10, 11, 13, 19)

A "recompute and compare" invariant can cite its derivation: "10. `saved_body`, `alternates` and `saved_kind` recompute from §7.5." Same for 19 ("resolves by §7.8"). **Saves 23 words** for item 10; similar for the others.

### Also noted, no change recommended

- A §3 entries `locator`, `source file` and `edition-ambiguous endpoint` define without citing their DM home (§7.3, §7.4, §7.5); add the cite.
- DM §6.4 "Current record" is a model derivation placed under the lake table; §7.5 reads it. Acceptable as is; moving it to §7.5 would shorten the reader's path by one hop.
- DM §9's key table is labeled normative but summarizes keys defined in §6–§8; marking §9 non-normative removes a second normative home at no cost.
- B §3.1–3.3 cells of 150–230 words (Fetcher, Body store, Receipt writer, Recovery importer, C3) are hard to scan in a table; a labeled list per component would read better. Formatting only; no words saved, so not ranked.
- DM §6.2 `group_path`'s element list (`li`, `tr`, `meeting-document`, `witness-document`, `document`) is a parser rule in a column note; a new publisher's grouping element means a DM edit. A "grouping elements" registry would make it one place. Judgment call; left to the owner.
- "contested edition" (DM §7.5, P §5.3) and "edition-ambiguous endpoint" (A §3) describe the same situation; use one.
- P §3's "R-check" and P §5.3's "raw check" are different checks with near-identical names; "derivability check" for the second.

---

## Change-cost summary

| Next change | Touches today | After the fixes |
|---|---|---|
| New publisher | source-family, capture-scope, recheck registries; DM §7.1 "(21 today)" count | registries only (count removed with S3) |
| New compressible or document format | DM §6.2 values; DM §5.1 and A §7.1 (S1); format-preference registry; sniff code | DM §6.2, DM §5.1, registry, code |
| New registry entry | registry file; DM §7.1 / §7.3 / §7.8 copies (S3) | registry file |
| New receipt shape | DM §5.2 aliases; DM §6.1 older-line bullet (S2) | DM §5.2, §6.1 |
| New release file | DM §8.1; A §10.1 table (S7); A §11.1; canary §10.3.5; inv 16/18 | DM §8.1, A §11.1, §10.3.5, inv 16/18 |

## Method

Each document was read in full once, then every rule, list and threshold that looked familiar was located with `grep` across the four files to confirm its homes; term collisions were counted the same way. No earlier review was read. No tracked file was changed; the only files written are in `review-6/editor/` (`ed6_savings.py`, this review).
