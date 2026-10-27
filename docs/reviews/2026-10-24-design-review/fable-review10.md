# Review 10 (Fable): the four engine-first design and plan documents

Worktree `/Users/mikewolfd/Work/wt/ct-ticket-audit`, branch `docs/ticket-audit-20261024`, HEAD 41f86b72.
Scope: the four files below, read blind (no reviews, scripts, code, data, tickets or git history).
Mode: evolutionary-refactoring skill, Audit. Nothing was modified.

| File | Words |
|---|---|
| `docs/engine-first-architecture.md` (ARCH) | 7,702 |
| `docs/engine-first-data-model.md` (DM) | 13,593 |
| `docs/plans/simplification-plan-20261024.md` (PLAN) | 8,709 |
| `docs/plans/bindings-20261025.md` (BIND) | 5,981 |

## Bottom line

**Grade: 76 / 100, C+** (scale used: A 90+, B 80–89, C+ 75–79, C 70–74).

The design is sound and unusually careful about the things the owner says matter: raw is content-addressed and create-only, the lake is append-only with anti-join work lists, publish is deterministic and content-addressed, and nothing reaches users before the site's own reader has loaded it. Most of what I would change is excess, not error. The deductions come from four places:

1. **One correctness-of-priorities problem.** The only ongoing raw loss the docs name (the weekly meeting job overwrites its source records; PLAN §1) is fixed in phase 2 (B14), behind the whole document switch. By the owner's own goal that is the first thing to fix, not the last.
2. **Three deletable mechanisms** that buy nothing the text can show: `legacy_pdf_checks` (changes no listing decision), completion rows (a sentinel-row hack that `readings` already avoids with a list column), and the `.gz` "logical body key" fiction inside every ID formula.
3. **Duplicate authorities**: older-receipt mapping rules live in both DM §5.2 and §6.1; the release file list is stated three times; the 404-reload rule five times; 26 registries where about 14 would do.
4. **Stale and fragile numbers**: ~280 measured counts, many repeated across docs, some already disagreeing (older bodies with a recorded size; the HTML/XML body population).

About 2,500 words can be deleted or folded outright, and another ~1,900 (the fixture table in PLAN §5.3) should move to the fixture directory it describes.

## Rubric

| # | Criterion | Score | Justification |
|---|---|---:|---|
| 1 | Goals and bottom line up front | 13/15 | Every abstract leads with decisions, goals and what lives elsewhere; PLAN's "First:" and "Owner actions" lines are exactly right. Lost two for the W3C ceremony (Status, ToC, duplicated BCP 14 paragraph) that pushes the first real section to line 40 in each spec. |
| 2 | Design correctness and invariants | 20/25 | Identity, immutability, idempotency and failure paths are mostly single-owner and consistent. Deductions: raw-loss fix ordered last (F1); one deterministic parser failure blocks publishing until a human writes provenance (F6); three 412 policies for one situation (F10); older-line mapping has two owners (F5); ARCH and PLAN disagree on which older bodies record a stored size (F12). |
| 3 | Simplicity and economy | 13/20 | Five concrete deletions available: `legacy_pdf_checks`, completion rows, the logical-key fiction, the second and third release file lists, and 12 of 26 registries. B13 (403 GB of writes) has no stated reason in any of the four docs. |
| 4 | Scalability reasoning | 12/15 | ARCH §16 names each step's order and the repeated work it accepts; the n-edge grouping and build-side rules are right. Lost three for not saying what the weekly raw check cannot see (F13), for a sampled M2 that cannot see the full link join (it says so, but the budget decision rests on it), and for not costing the per-publish 5.5M URL resolutions it chooses to repeat. |
| 5 | Plan executability | 11/15 | Tracks have dependencies and testable done-whens; §8 pairs each unknown with the step that settles it and a pre-committed decision rule. Lost four for the phase ordering (F1), for the fixture table living in the plan instead of beside the SQL (F9), for the K-numbered seeds that only resolve through a document outside the set, and for "the rules give the right documents" as a done-when. |
| 6 | Writing quality | 7/10 | Dense, consistent vocabulary, scannable tables. Lost three for repetition across docs (the same fact in up to five places), nested 70-word sentences in DM §6.1 and §7.3, and a normative spec that cites plan step IDs (B0, B13, A11, E1). |
| | **Total** | **76/100** | **C+** |

## Grade per document

| Document | Grade | One line |
|---|---|---|
| ARCH | B | The best of the four: short, decides behaviour, honest about cost. Carries a second copy of the file list and of the reader's join graph that DM owns. |
| DM | B- | The most correct document, and the one that most needs a diet: §5.2 and §6.1 split one mapping, the registry table has 26 rows, and measured counts sit inside schema notes. |
| PLAN | C+ | Good track structure and uncertainty table; the phase split puts the one raw-loss fix last, and 2,000 words of fixtures and 400 of parity predictions belong in files the plan should cite. |
| BIND | B- | Does what it says and rots by design (pinned line numbers). Its deletion ledger is the right artifact. Not re-reviewed line by line since its evidence is the code I was told not to read. |

## Findings, ranked by severity

Each gives location, evidence, mechanism, bounded fix (delete > merge > fold > rewrite), words saved, and a label.

### F1. The only ongoing raw loss is fixed in phase 2 — High — confirmed-from-text

- **Where:** PLAN §1 line 34; §4 line 73; B14 line 274–276; F2 line 363.
- **Evidence:** "the versions of the weekly meeting job's source records from 2026-10-05 to 2026-10-26, which that job overwrites on each run, are kept in a local content-addressed batch until B14 imports it; later versions are kept only by re-running the rescue." Phase 1 keeps "the weekly meeting job, whose inventories seed capture until B14." B14 is phase 2.
- **Mechanism:** The owner's first goal is that raw source data is never lost or corrupted. The plan names one place where it is being lost weekly, keeps the job running through all of phase 1, and relies on a manual local rescue in the meantime. Every week between now and B14 is a week of versions kept only on one laptop.
- **Fix (fold, into §4 item 1):** Treat it as the raw-writer patch it is. Alongside "the old writers are patched and B0 runs", add: the weekly job writes each run's source records create-only under a date-shaped receipt prefix (one small patch, no new component), and the local batch is imported now as one import run. B14 then only moves fetching into the fetcher. Nothing in phase 1 depends on the records' shape, since `meeting_records` is phase 2.
- **Words:** +40 in PLAN §4, −30 in §1.

### F2. `legacy_pdf_checks` changes no decision in phase 1 — High (simplicity) — confirmed-from-text

- **Where:** DM §5.3 line 198; §7.3 lines 519–522, 565; PLAN D2 line 323, B7 line 265; BIND line 241.
- **Evidence:** DM §7.3: unchecked PDFs "count as documents until B13's copy records a check". DM §5.3: `legacy_pdf_checks` records `opened (true only)`. DM §7.3 `record_role`: `damaged` needs `intact is not true and intact_basis <> 'unchecked'`.
- **Mechanism:** A legacy record can only make `intact` true, which makes the body a `document`. An unchecked PDF is also a `document`. So the 5,978 legacy records move no body in or out of the list; they change only `intact_basis` and one count in a per-release report. For that, the plan adds a provenance kind, a one-time import that must finish before the old readings are deleted, a fourth branch in the `intact` precedence, and three doc entries. After B13 every older PDF has a `copy` record and the branch is dead anyway.
- **Fix (delete):** Remove the `legacy_pdf_checks` kind, the D2 import step, the BIND clause and the `'legacy'` basis. `intact` becomes: copy, else read, else capture. Add one sentence after B13: "the `capture` basis for older rows is then dropped too", so the temporary coexistence has its removal condition.
- **Words:** ~150 across DM, PLAN and BIND.

### F3. Completion rows are a sentinel-row hack that the `readings` design already avoids — Medium-High — confirmed-from-text

- **Where:** DM §6 lines 215–219; §6.5 `is_completion` line 380; §6.7 line 413; invariant 5 line 936; §7 line 425 ("with completion rows ... excluded"); PLAN D4 line 328; BIND line 299.
- **Evidence:** "one completion row: `is_completion = true` ... its other PK columns at their type's zero value (`''` or `0`) and every other column null, so every non-PK column but `is_completion` is nullable." Compare `readings.links`: "empty when the page has none."
- **Mechanism:** The meeting and appearance tables are keyed per *output* (event, witness), so an input with zero outputs needs a fake row, which forces every non-PK column nullable, makes every model query filter the sentinel, and adds an invariant, a producer rule and a work item. `readings` solved the same problem by keying per *input* and holding the many-valued fact as a list. The appearance PK `(record_sha, parser_version, name_key)` is also lossy: "rows of one input sharing a `name_key` collapse to the first", so two witnesses with one normalized name on one panel become one.
- **Fix (rewrite the two schemas, delete the concept):** Key `meeting_records` and `appearance_records` by `(record_sha, parser_version)` with `status` like `readings` and a `meetings`/`appearances` list column; the model unnests. Delete the "Completion rows" paragraph, both `is_completion` columns, invariant 5, the D4 completion invariant and the BIND item. The tables are "tens of thousands of rows", so the lost per-event pruning costs nothing.
- **Words:** ~150. **Data check:** none needed; the one cost is an `unnest` in the model, which M2 can time.

### F4. B13 writes 403 GB of raw with no reason stated in any of the four docs — Medium-High — needs a data check

- **Where:** ARCH §7.1 line 253; §11.5 lines 457–458; DM §5.1 line 110; PLAN B13 lines 271–273; BIND line 203.
- **Evidence:** ARCH §11.5 already handles every `.gz` body: "fetched and unpacked with the browser's `DecompressionStream` ... those whose original size exceeds 100 MB (313, up to 1.19 GB) are offered as a labeled compressed download." PLAN B13: "the largest raw write in the plan ... about 260,175 uploads and 403 GB once decompressed (about $72 a year)." No sentence says why a `.pdf` copy is needed.
- **Mechanism:** The owner's rule is to defer big re-read jobs unless truly needed. B13 is the biggest raw job in the plan, and it drags along a third physical suffix, the `suffix(body)` rule, the `copy` intact basis, a one-off component and a verification-record variant. The plausible reasons (native PDF viewer instead of a Blob; Range reads into large PDFs; verifying 260k bodies on the way, which B10 could do without writing) are never written down, so a reader cannot tell whether the job is load-bearing.
- **Fix (rewrite one sentence, then decide):** State the reason in ARCH §7.1 or delete B13. If deleted: B10 verifies gzip PDFs by reading them (same 365 GB of reads, no writes), `suffix(body)` loses its first branch, and `.pdf` leaves DM §3 and §5.1.
- **Measure:** on a mid-range phone, time-to-first-page for a typical 5–20 MB gzip PDF through `DecompressionStream` versus a direct `.pdf` open; and the share of saved-file opens whose body is a PDF over 100 MB. If the Blob path is within the §11.2 targets, delete B13.
- **Words:** ~300 if deleted; +30 if kept.

### F5. Older-receipt mapping has two owners: DM §5.2 and §6.1 — Medium — confirmed-from-text

- **Where:** DM §5.2 lines 125, 149, 150, 167–172, 180 ("Older lines: ..." on nine fields); §6.1 lines 257–269 (the ingest mapping bullets).
- **Evidence:** §5.2 `member_path`: "Older lines: `original_path` on a `captures[]` entry whose `pointer` passes through `archive_members`; a `file_references[]` entry's `original_path` is a retained file's local path (522,504 entries), never a member path." §6.1: "Older lines (all 2,596,054 today) keep their fields under `record`, in shapes the ingest mapping reads one by one."
- **Mechanism:** §5.2 is the receipt writer's contract (what a new line must carry). The ingest mapping is "versioned with the table" and owns how older shapes are read. Splitting older-shape rules between them means a new older shape found by M2's census is edited in two tables, and a reader of §5.2 cannot tell which sentences bind the writer. It is also why §5.2 is the DM's largest section (1,000 words).
- **Fix (fold):** Move every "Older lines:" clause and the recovery-import fallbacks into §6.1's mapping list. §5.2 then describes only the new line, and "Older lines keep their `links`; the model does not read them" becomes one bullet in §6.1.
- **Words:** ~150 net (the moved clauses lose their framing).

### F6. One deterministic parser failure blocks every publish until a human writes provenance — Medium — confirmed-from-text

- **Where:** DM §6.2 line 283; §7.1 line 429; ARCH §12 line 490.
- **Evidence:** "`error` is a deterministic rejection of the input; an operational failure writes no row, so the input stays on the work list until it succeeds or an `unreadable` decision drops it." "Publish MUST refuse when a pinned version's work list is not empty."
- **Mechanism:** Whether a failure is "deterministic" is decided by the parser author, not observed. A body that makes the content extractor hang, OOM or panic is an operational failure every day, keeps the work list non-empty, and stops publishing until someone writes an `unreadable` record. The daily pipeline's availability then depends on a human's response time to one pathological page.
- **Fix (fold one rule into DM §6.2):** A producer retries a failed input once in the same run; a second identical failure is recorded as `status = error, error_type = 'crash'` (deterministic by observation) and reported per release. `unreadable` stays for inputs a person wants dropped from retries at a later version.
- **Words:** +35. **Data check:** on the 2,000-page M2 sample, count extractor failures by type; if zero, keep the rule but still add the sentence, since the cost of the failure mode is total.

### F7. Twenty-six registries where about fourteen would do — Medium — confirmed-from-text

- **Where:** DM §7.1 lines 441–468.
- **Evidence:** Seven registries feed only `record roles` (error words, error URLs, wrapper markers, page thresholds, source-record roots, API endpoints, feed roots), all "versioned by profile". Three feed only `url_key` and link targets (URL wrappers, strip-list, URL repairs). Two feed only renditions (generic stems, format preference). "Registries are never stored in the lake, so a change rewrites nothing there."
- **Mechanism:** Separate versioning buys nothing here: no work list keys on a registry version, and any registry change already changes the profile and the input identity. Each registry is a file, a digest in the profile, a sample test, a table row and a BIND seed row, so a new role signal costs five edits where one row in a `record-role` registry with a `kind` column would do. This is cloned policy with one consumer, one owner and one version cadence, which is the case the skill says to consolidate.
- **Fix (merge):** `record-role` (kind: error-word, error-url, wrapper-marker, threshold, source-record-root, api-endpoint, feed-root), `url` (kind: wrapper, strip, repair), `rendition` (kind: generic-stem, format-preference). Keep the raw-writer registries, `file shapes`, `meeting sources`, `import runs`, `recovery kinds`, `recheck intervals`, `capture scope`, `committee codes`, `publisher kinds`, `display facts` and `filename parameters` separate, since each has a distinct consumer or version cadence.
- **Words:** ~120 in the table; ~80 in BIND §4.

### F8. The release file list is stated three times — Medium — confirmed-from-text

- **Where:** ARCH §10.1 table lines 369–384; ARCH §11.1 line 439 (the thirteen file names in prose); DM §8.1 table lines 834–854; plus DM §9's key table and ARCH §11.6's join list (F11).
- **Evidence:** ARCH §10.1 and DM §8.1 both list the fourteen files; ARCH §11.1: "then `detail`, `links`, `urls`, `sources`, `recoveries`, `meetings`, `witnesses`, `committees`, `members`, `rosters`, `bills` and `nominations` as needed."
- **Mechanism:** Adding or renaming a file edits three lists plus two join descriptions. The ARCH abstract already says DM "holds every schema"; the ARCH table is a purpose-column copy of it.
- **Fix (delete):** Remove the ARCH §10.1 table and keep its four bullets with "files: [[DATA-MODEL]] §8.1". Replace the §11.1 list with "then the other release files as needed". DM §8.1 can carry a `Purpose` column if that text is missed.
- **Words:** ~220.

### F9. The fixture table lives in the plan instead of beside the SQL — Medium — confirmed-from-text

- **Where:** PLAN §5.3 lines 145–197 (52 rows, ~1,900 words of a 1,998-word section).
- **Evidence:** "each fixture below is written with its expected outcome before any SQL, so the table is the acceptance sheet. S adds a row for each format ... the table does not yet name."
- **Mechanism:** The table is the fixtures' manifest, and it grows with every rule, on a different lifecycle from the plan. Once E1 writes the fixtures, two authorities exist and the plan's copy goes stale on the first added case. It is also what makes PLAN unreadable in one sitting.
- **Fix (merge out):** Move the table now into the fixture directory's manifest (one file, the same columns, the SQL tests read it). PLAN §5.3 keeps the rules for S1/S2 and cites the manifest. The labeled sample, edition count and raw-only check paragraphs stay.
- **Words:** ~1,900 moved out of PLAN, not deleted.

### F10. Three 412 policies for one situation — Low-Medium — confirmed-from-text

- **Where:** ARCH §7.1 line 245 (bodies: "no HEAD, download or comparison"); ARCH §10.3.4 line 419 (releases: "MUST be checked ... with one HEAD"); BIND line 213 (PDF copier: "compare the existing object's ETag with the expected MD5"); BIND C5 line 376.
- **Mechanism:** All three keys are content-addressed: the body key is the SHA-256 of the bytes, the release prefix is the SHA-256 of the files' digests, and the `.pdf` key is derived from its original's SHA-256. The reasoning that makes a body's 412 a success without a HEAD makes the other two the same. Keeping three rules means a reader must work out why they differ, and there is no reason.
- **Fix (fold):** One sentence in ARCH §7.1: "A 412 on any content-addressed key is success and needs no HEAD; this covers bodies, `.pdf` copies and release files." Delete the HEAD clause from §10.3.4 and BIND, and §13 item 5's exception list shrinks to the `.gz` twin HEAD.
- **Words:** ~60.

### F11. ARCH §11.6 bullet 3 restates DM §9's join graph — Low-Medium — confirmed-from-text

- **Where:** ARCH §11.6 line 468 (180 words from "A hearing lists its witnesses ..." to "... for member positions, money and lobbying"); DM §9 key table line 923 ("release → release").
- **Mechanism:** Two prose authorities for which key joins which file. A new entity edits both (see the next-change question).
- **Fix (delete from ARCH):** Keep the filter MUST and "documents sharing a `version_keys` entry are shown as each other's versions"; replace the join list with "joins as [[DATA-MODEL]] §9 keys them".
- **Words:** ~150.

### F12. ARCH and PLAN disagree on which older bodies record a stored size — Low-Medium — needs a data check

- **Where:** ARCH §7.4 line 275: "Older lines record the stored bytes' SHA-256 and size, never their MD5 (all 1,036,256 bodies)"; PLAN B9 line 267: "from the receipts, else the old index for the 364,193 bodies whose receipts record none."
- **Mechanism:** The listing baseline's only integrity test for older bodies is size against recorded size. If 364,193 bodies have no recorded size in raw, that number comes from the old index, which is a derived table the plan says to delete and principle 1 says raw must not depend on. Either ARCH's "all" is wrong or PLAN's fallback is unnecessary.
- **Fix:** Measure, then fold the true statement into ARCH §7.4 and cite it from B9.
- **Measure:** count capture entries over all 1,036,256 body SHAs whose creating line records a stored size (any shape). If 364,193 lack one, B9 must write the old index's sizes into the listing-baseline verification record so raw stops depending on the index.

### F13. The weekly raw check mostly confirms R2 against itself — Low — confirmed-from-text

- **Where:** ARCH §7.4 line 277; invariant 2 line 933.
- **Evidence:** "It confirms that every recorded key exists and that every stored body has the size and ETag its creating line or verification record gives ... 25 random bodies are downloaded and checked end to end."
- **Mechanism:** The ETag in a LIST is R2's record of what it received, which the create-only PUT with `Content-MD5` already proved; the LIST cannot see bit rot. The 25-body sample is the only end-to-end check, and at 25 a week over 1.04M bodies a given body is read once in roughly 800 years. That is consistent with "a provider-side loss is the accepted risk", but the paragraph reads as if it verifies content. What the check does see: a missing object, an object replaced with different bytes (the lock prevents this), a late receipt. Say so.
- **Fix (rewrite one sentence):** "The listing proves presence and that nothing was replaced; the 25-body sample is the only content check, and R2's durability is the accepted guard against bit rot."
- **Words:** +20.

### F14. Measured counts embedded in schema notes — Low — confirmed-from-text

- **Where:** DM §6.1 lines 231, 233, 234, 235, 248, 262, 264; §6.2 line 305; §7.2 line 501; §7.3 lines 565–570; §7.5 lines 675–677; and the three HTML/XML body counts that cannot be reconciled from the text: 287,765 "the server labels HTML or XML" (DM line 305), 214,041 "good-fetched HTML and XML bodies" (DM line 501), 289,179 "the page readings" (PLAN line 47).
- **Evidence:** PLAN §8 line 409: "each review round found 10–20 of about 370 wrong."
- **Mechanism:** A count inside a column note is a fact about one snapshot; the next snapshot makes the normative text wrong without any rule changing. Repeated counts (1,036,256 ×7, 403 GB ×5, 199,156 ×3) are synchronized edits. Three populations for "HTML/XML bodies" with no definition of each leave a reader unable to know which one the 4.2M link estimate scales from.
- **Fix (fold):** Keep ARCH §5 and DM §5.1's size rows as the only homes for counts; everywhere else write the population's definition and cite the measurement directory. Define the three HTML/XML populations once, in DM §6.2.
- **Words:** ~250. **Measure:** one script from one snapshot producing all three HTML/XML counts, so their relation is known.

### F15. The logical body key keeps a `.gz` fiction inside every ID — Low — confirmed-from-text

- **Where:** DM §3 lines 57–58; §7.4 line 578; §7.5 line 653; PLAN E3 line 340; BIND lines 401–403.
- **Evidence:** "The string `bodies/sha256/<aa>/<sha>.gz` for a body, whatever its physical key: the body's input to the ID formulas." "`document_id` keeps today's formula."
- **Mechanism:** Nothing outside the model holds a `document_id` ("a document's ID is recomputed, not stored"; reviews target link keys; `list` has no ID), and E4's parity is "keyed by source evidence", not by ID. So the only consumer of ID stability is the golden-vector test against the old code. After the switch the `.gz` path string, the logical/physical distinction and the vectors are sediment.
- **Fix (fold a removal condition):** In DM §7.5: "After E4 passes, `document_id` hashes the sorted body SHA-256 bytes directly and the logical key is retired." Delete the term and the vectors then. (`record_sha` still needs canonical JSON, so the engine's `json_array` stays.)
- **Words:** ~80 later.

### F16. One rule, many homes: the 404 reload and the test-only ratchet — Low — confirmed-from-text

- **Where:** 404 reload: ARCH §11.3, §15 item 6, DM invariant 21, PLAN A4, BIND line 434. Ratchet: ARCH §13 last paragraph, §15 item 7, PLAN B11, BIND §2 preamble, BIND §6.
- **Mechanism:** Invariant 21 is a reader behaviour in a data-model invariants list; the others are citations that restate the rule. A change to the reload rule (say, "twice") is five edits.
- **Fix (delete):** Invariant 21 and the restatements; ARCH §11.3 owns the reload, ARCH §15 item 7 owns the ratchet; others cite by section.
- **Words:** ~100.

### F17. Normative specs cite plan step IDs — Low — confirmed-from-text

- **Where:** DM lines 182 (B0), 248 and 565 (B13), 567 (E1), 857 (A11); ARCH §17.2.
- **Mechanism:** An Editor's Draft that says "until B13's copy records a check" goes wrong when the plan renumbers, and a reader of the spec alone cannot resolve B13. The condition is what the spec needs; the step is the plan's business.
- **Fix (rewrite in place):** "until the body's `.pdf` copy has a verification record", "until the labeled sample fixes the list", "the heap test of the first engine-built release". PLAN keeps citing DM.
- **Words:** 0.

### F18. Ceremony — Low — confirmed-from-text

- **Where:** ARCH and DM "Status of This Document", "Table of Contents", the BCP 14 paragraph in both (DM §2 could cite ARCH §2); PLAN and BIND tables of contents.
- **Mechanism:** ~450 words before the first decision, for a greenfield project with one owner. Conformance classes are used by ARCH §6's table and earn their place; the rest does not.
- **Fix (delete):** the four tables of contents (renderers generate them), both Status sections (fold the one measured-snapshot sentence into the abstract), DM's BCP 14 paragraph.
- **Words:** ~300.

### F19. Small items — Low — confirmed-from-text

- DM §8.1 line 837: "*est.* well under the earlier 55–70 MB, most of which was the dropped reading and filename folds" refers to a design that is not in these docs; write "measured with F0". (~25 words)
- DM §6.2 `format` "on every row" of `readings`: the model reads `r[sniff].format` only, so the copy on html/xml/json rows is a derived value stored, against principle 7. Either say it is for partition pruning or drop it.
- DM §6.3 claims `catalog_version` "covers ... the effective-filename rule", but the filename-parameter registry that rule reads is "versioned by profile" (§7.1 table). Put the registry's digest inside `catalog_version` or drop the claim.
- DM §3 "meeting key, chamber" holds a mapping rule (five spellings) in a glossary entry; move it to §6.5 where chamber is read.
- ARCH §7.1 line 247 "local disk writes a temporary file and links it into place" is adapter implementation, which BIND already states; delete from the spec. (~20 words)
- ARCH §12 holds eight unrelated rules; "Pinned engine" belongs in §14 and "Resources" in §13 item 6.
- DM §7.8 names a PK "(receipt_key, receipt_line, capture_index)" that the release file does not carry; say "identity" or list the columns it does carry.
- BIND line 98 silently narrows capture scope ("event pages that only its POST calendar API finds ... are no longer captured"); that is a decision for PLAN §7 "Considered, not chosen", with the count.

## Keep as is

These are sound and should not be touched:

- Content-addressed bodies under `bodies/sha256/<aa>/<sha>` with one create-only PUT and `Content-MD5`, no multipart, and the one HEAD for the `.gz` twin: justified exactly as long as two key forms coexist, and O(new bodies) per day.
- The bucket lock per prefix, separate tokens per job, and "only maintenance deletes".
- Receipts written create-only after their bodies, never-reused run IDs, and the accepted crash-between-body-and-receipt loss.
- The append-only lake with anti-join work lists, "an input that produced nothing still needs a row" (for `readings` and `filename_readings`, via `status`), the snapshot-asserting commit with a three-try reload-and-recompute, and "nothing depends on physical sort order".
- Reference inputs read from pinned spicy-regs generations rather than copied into the lake, with the mutual pin lists.
- Input identity over receipt keys, provenance ETags, generation digests and the profile, excluding snapshot IDs; the early skip; the content-addressed release ID; the empty-`list` refusal.
- Canary with the site's own reader before an `If-Match` pointer flip; immutable release files and a `no-store` pointer; the one CI concurrency group; retention from the pointer with no reference counting.
- Determinism as an engine property (unique sort keys, fixed re-batching, pinned writer settings) and the honest note that determinism is not dedupe.
- One reader module accepting N and N−1 schema versions; `list` decoded column by column in a worker; offset-index Range reads with a per-session byte cache.
- One node per body, fingerprint or rendition group so a group of n files costs n edges; the edition rule ("an edition never joins another"); `placeholders` at a measured k.
- `link_key` as the first 8 bytes of a real body's SHA-256; `lookup_url` fixed by the spec and never by a registry; `url_key` as the one join key with the explicit list of places that must not use it.
- The effective filename as one SQL definition shared by producer and model.
- `list` with no ID, linked by row number; `detail` and `sources` sharded only at a stated growth threshold.
- ARCH §6's component table (one index of class, contract and adapters) and §16's cost table with its named repeated work.
- PLAN §8's uncertainty table, each row with the step that settles it and what it decides; M1 and M2 as measurements with decision rules committed before they run.
- PLAN §3's runner rule, the `wc -l` rule for deletions, and B0's backup-verify-rewrite-reverify procedure.
- BIND's Bind/Adapt/Build/Seed taxonomy, §5's "propose a use before deleting", and §6's deletion ledger.

## The next-change question

**Where would a new reference entity, say `treaties.parquet` (treaties already appear in `subject_keys`), be added, and how many places change?**

Today, across the four docs: DM §6.4 (a spicy-regs table row), §7.11 (a relation), §8.1 (a file row, and a `list` key column if filterable), §9 (the diagram and the key table), invariant 16; ARCH §10.1 (the file table), §11.1 (the file list), §11.6 (the filter MUST and the join sentence), §8.5 (the family list), §6 (the overview diagram); PLAN §4 phase 2, §5.3 (an S2 fixture row), A9; BIND site pages. **About fourteen edits in four documents.**

After F8 and F11, the same change is DM §6.4, §7.11, §8.1 and §9, plus one fixture row: **five edits, four of them in one document**, with ARCH and the reader unchanged because the reader "offers a connection only when its file is present" (DM §8.1). That is the localized answer the design already half-has.

For contrast, the other real axis, a new source family or committee site layout, is already localized: four registries (source families, capture scope, host pacing, meeting sources), one parser rule if the layout is new, and one fixture row, with no spec edit. That part of the design is right.

## Residual

- I did not verify BIND's line references or component counts; its evidence is the code, which this review was told not to read.
- Word-saving estimates are by section size, not by a rewrite; the total of ~2,500 deletable and ~1,900 movable is an order-of-magnitude figure.
- Data checks to run, in order of what they unblock: F12 (recorded stored sizes), F4 (gzip PDF open time on a phone), F14 (the three HTML/XML populations), F6 (extractor failure count on the M2 sample).
