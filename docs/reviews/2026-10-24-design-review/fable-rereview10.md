# Review 10 (Fable), second pass: the docs after commit 47c35f57

Worktree `/Users/mikewolfd/Work/wt/ct-ticket-audit`, `47c35f57` on top of `9c7db41c`. Read: the diff between those commits and the five current files. Same rubric, same scale (A 90+, B 80–89, C+ 75–79, C 70–74), evolutionary-refactoring Audit mode; nothing modified.

| File | Before | After |
|---|---:|---:|
| ARCH | 7,702 | 7,454 |
| DM | 13,593 | 13,479 |
| PLAN | 8,709 | 7,228 |
| BIND | 5,981 | 5,966 |
| fixtures (new) | — | 1,700 |
| Total | 35,985 | 35,827 |

## Bottom line

**Grade: 84 / 100, B** (was 76, C+).

The edits did what they set out to do. The one ordering problem is gone (B15 is first), the three deletable mechanisms are deleted or folded, the duplicate authorities for the file list, the join graph and the older-receipt mapping are now single, and every plan step ID has left the specs. The owner's departures are all defensible and three of them are better than what I proposed (the capture-scope narrowing as an open uncertainty; the B13 reason; DM §8's one-paragraph purpose list).

What the edits introduced, in order of weight: a new tension between the crash rule and the byte-identical-rebuild invariant; a sentence in ARCH §7.1 that contradicts §11.5's own number; B15 calling every weekly run an "import run", which the data model defines as something else; and three small dangling references. None is hard to fix; together they are about 100 words.

The total word count barely moved (−158 net, −1,858 across the four original docs) because DM's merges added as much table as they removed and the owner chose to keep counts that justify rules. That is a defensible choice; the docs are not shorter, but they are tighter.

## Rubric

| # | Criterion | Before | After | Justification |
|---|---|---:|---:|---|
| 1 | Goals and bottom line up front | 13 | 14/15 | Status, ToC and the duplicated BCP 14 paragraph are gone; each doc's first screen is now its abstract and first section. BIND keeps a Status section that carries real content. |
| 2 | Design correctness and invariants | 20 | 21/25 | B15 puts the raw-loss fix first; the 412 rule is one rule plus one justified exception; older-line mapping has one owner. New: the crash rule can break invariants 1 and 4 (N1); ARCH §7.1 contradicts §11.5 (N2); B15's "import-run receipt" misuses a defined term (N3). |
| 3 | Simplicity and economy | 13 | 15/20 | `legacy_pdf_checks`, completion rows, the ARCH file table and the §11.6 join list are gone; 26 registries are 17 with a stated rule for when lists share one. Kept by decision: B13 (now with a reason), the `.gz` logical key, most counts. DM shrank only 114 words. |
| 4 | Scalability reasoning | 12 | 13/15 | The raw check now says what it cannot see; the three page populations are defined once and nest. The sampled M2 link join and the per-publish 5.5M resolutions are unchanged (accepted, measured later). |
| 5 | Plan executability | 11 | 13/15 | B15 has an order, an owner action, a pause rule, a done-when and a successor. Fixtures moved out with a removal condition. Lost: B15's mode ambiguity (N3), a dangling "D4 completion invariant" in BIND (N4), and "the rules give the right documents" is still a done-when. |
| 6 | Writing quality | 7 | 8/10 | The repeated file lists, join graph, 404 rule and plan IDs are gone. New small repetition in ARCH §7.4 (N7) and a 90-word registry cell. |
| | **Total** | **76** | **84/100** | **B** |

## Grade per document

| Document | Before | After | One line |
|---|---|---|---|
| ARCH | B | B+ | Leaner and single-owner now; carries the two new wording faults (N2, N7) and one stale example (N5). |
| DM | B- | B | The §5.2/§6.1 split, completion rows and legacy checks are fixed; the registry merge is right. N1 is its one new design tension. |
| PLAN | C+ | B | B15 first, fixtures out, parity list intact. N3 and the done-when wording are what remain. |
| BIND | B- | B- | Correctly re-pointed except one dangling contract-suite reference (N4). Unchanged otherwise, as expected. |
| fixtures | — | B+ | Does one thing, says when it stops being the authority. Fine. |

## Verdicts on F1–F19

| # | Finding | Verdict | Note |
|---|---|---|---|
| F1 | Raw-loss fix ordered last | **Fixed** | PLAN §4 item 1 "B15 first"; B15 at line 207 with a done-when at line 210; abstract names the owner actions. Two wording nits remain (N3, N8). |
| F2 | `legacy_pdf_checks` has no effect | **Fixed** | Kind, import step, BIND clause and `'legacy'` basis removed; DM §7.3 line 581 states why opens are not borrowed. |
| F3 | Completion rows | **Fixed** | DM §6 "One row per input"; `meetings`/`appearances` list columns; invariant 5 gone; model unnests. One dangling reference (N4) and one orphaned rule (N6). |
| F4 | B13 unjustified | **Partly fixed, departure accepted** | ARCH §7.1 line 229 now gives the reason (plain links the browser's viewer opens; large PDFs never pass through the page). That is a product decision, so my data check is moot. The new sentence contradicts §11.5 (N2). |
| F5 | Older-line mapping had two owners | **Fixed** | §5.2 binds new lines only (line 353 says so); all older-shape clauses are in §6.1's mapping list. |
| F6 | One bad input blocks publishing | **Fixed** | DM §6 lines 194–196; ARCH §8.3 line 283; a fixture row. Introduces N1. |
| F7 | 26 registries | **Fixed** | 17, with the rule "lists read by the same rules at the same version share one registry as entry kinds" (DM §7.1 line 481). 17 versus my 14 is a difference of taste, not structure. |
| F8 | File list stated three times | **Fixed** | ARCH §10.1 table and §11.1 list deleted; DM §8 intro carries the purposes once. |
| F9 | Fixture table in the plan | **Fixed** | `docs/plans/fixtures-20261026.md`, with "E1 moves this table into the fixture directory as its manifest, and it is edited there from then on." |
| F10 | Three 412 policies | **Partly fixed, departure accepted** | Release HEAD gone (§10.3.4, BIND C5). The copier's HEAD stays with a reason (unrecorded copies from today's capture). One rule plus one named exception is fine. |
| F11 | ARCH §11.6 restated DM §9 | **Fixed** | Line 424 now cites DM §9; `witnesses` added to DM §9's key row. |
| F12 | ARCH/PLAN disagreed on recorded sizes | **Fixed** | ARCH §7.4 line 251: 672,063 from receipts, 364,193 from the old index, baseline becomes raw's record. Minor layering nit (N5b). |
| F13 | Raw check's blind spot unstated | **Fixed** | ARCH §7.4 line 255. Creates a small repetition with the next paragraph (N7). |
| F14 | Counts in schema notes; three page populations | **Partly fixed, departure accepted** | Populations defined once in DM §6.2 (nested, so not contradictory; I withdraw "irreconcilable"). §6.1's counts stripped; rule-justifying counts kept by decision. |
| F15 | `.gz` logical key in every ID | **Not fixed, deferred** | Validator marked it unchecked pending the 16-hex ID decision. From the text, links carry `link_key`, not `document_id`, and "a document's ID is recomputed, not stored" (DM §8.1), so the finding stands as confirmed-from-text; deferring it costs nothing until E4. |
| F16 | 404 rule in five places; ratchet in four | **Fixed** | Invariant 21 deleted; ARCH §11.3 owns the reload, §15 item 6 tests it, BIND lists the work; ARCH §13 now cites §15's ratchets. |
| F17 | Specs cite plan step IDs | **Fixed** | No `B0`, `B13`, `E1`, `A11` or `[[IMPLEMENTATION-PLAN]] X` remains in ARCH or DM. |
| F18 | Ceremony | **Fixed** | Four ToCs, two Status sections and DM's BCP 14 paragraph gone (~300 words). |
| F19 | Small items | **Partly fixed, departures accepted** | Done: detail-size wording, local-disk sentence, Pinned engine → §14, Resources → §13.6, `format` on sniff rows only, `catalog_version` covers the filename-parameter registry, capture-scope narrowing → PLAN §8 (better than my suggestion). Kept by decision: chamber map in §3, §7.8's PK. Not done: ARCH §12 example (N5). |

Tally: 13 fixed, 5 partly fixed with accepted departures, 1 deferred, 0 made worse.

## New findings, ranked

### N1. The crash rule can break the byte-identical-rebuild invariant — Medium — confirmed-from-text

- **Where:** DM §6 line 195; invariant 1 (line 915) and invariant 4 (line 918).
- **Evidence:** "A parse that crashes, hangs or exceeds [the version's time and memory bounds] is retried once in the run, then recorded as `error` with `error_type = 'crash'`." Invariant 1: "A parser version re-run on a sample of its inputs reproduces its rows." Invariant 4: "a maintained lake and a clean rebuild from the same raw at the same profile give byte-identical releases."
- **Mechanism:** A hang or memory overrun is a property of the run, not of the input: a slower runner or a busier day produces a `crash` row where a clean rebuild produces a `completed` one. That input's body then changes role between the maintained lake and the rebuild, and the two releases differ. The rule I asked for created this; the fix I should have included is the reconciliation.
- **Fix (fold, ~40 words in DM §6):** "A `crash` row at a pinned version is final for that version. The rebuild check of invariant 4 copies `crash` rows from the kept table version instead of re-parsing them, and reports their count; a new version retries them." Invariant 1 adds "except `crash` rows".
- **Data check:** none; it is a determinism argument.

### N2. ARCH §7.1 says every non-PDF `.gz` body unpacks in the browser; §11.5 says 313 do not — Low-Medium — confirmed-from-text (one data check)

- **Where:** ARCH §7.1 line 229: "other `.gz` bodies are small enough to unpack in the browser (§11.5)". ARCH §11.5 line 417, under "Other `.gz` bodies": "those whose original size in `detail` exceeds 100 MB (313, up to 1.19 GB) are offered as a labeled compressed download."
- **Mechanism:** §11.5's bullet structure puts the 313 among the non-PDF bodies, so the new §7.1 sentence is false by the doc's own count. A reader deciding whether B13 is load-bearing is told the opposite of what §11.5 shows.
- **Fix (delete the clause):** end the §7.1 sentence at "never pass through the page"; §11.5 already owns what happens to other bodies.
- **Measure:** how many of the 313 are PDFs. If all are, the clause is true and §11.5's bullet is in the wrong place instead.

### N3. B15 calls every weekly run an "import run", which the model treats as a bulk load of older captures — Low-Medium — confirmed-from-text

- **Where:** PLAN B15 line 207: "each run also writes every source record it saves as bodies and one import-run receipt ([[DATA-MODEL]] §5.2)". ARCH §3: "import run: A bulk run that loaded older captures, listed in the import-run registry." DM §7.4 line 567: `first_fetched` is "Over its `mode = fetch` rows outside import runs"; DM §7.1 line 445: the import-run registry holds "`run_id` and date of each bulk import run".
- **Mechanism:** `mode` has two values, `fetch` and `retained_import`; "import run" is neither, it is a `fetch` line whose `run_id` the registry lists so its dates do not count as capture dates. The rescued batch is exactly that. The ongoing weekly runs are real fetches at a real time and should be plain `fetch` lines, or their fetch times are discarded. Today the effect is small (meeting records make no documents, and `meeting_records`' "current record" order still reads their `retrieved_at`), but a classmate implementing B15 from this sentence will write the wrong mode or ask.
- **Fix (rewrite one clause):** "each run writes its records as bodies and a `fetch` receipt; the rescued batch is imported once as a `fetch` receipt whose `run_id` goes into the import-run registry, the way the 2026-09-30 assembly was."

### N4. BIND cites a contract suite that no longer exists — Low — confirmed-from-text

- **Where:** BIND line 297: "*Contract suite:* D4 completion invariant; the S2 witness and meeting fixtures".
- **Mechanism:** Invariant 5 and completion rows were deleted; nothing named "D4 completion invariant" remains in PLAN or DM.
- **Fix (rewrite):** "*Contract suite:* the parser re-run invariant (invariant 1) on a record that yields no meeting or witness; the S2 witness and meeting fixtures." The new fixture row "a witness list naming none" already exists.

### N5. Two leftovers of the removed `fingerprint` producer — Low — confirmed-from-text

- **Where:** ARCH §12 line 448: "A step whose work list exceeds it, such as a registry change that adds thousands of fingerprint candidates, is left to a backfill". ARCH §6 line 195: "Parsers (sniff, html, xml, json, fingerprint)".
- **Mechanism:** §12's pipeline line and §16 no longer run a fingerprint step, and §8.3 says "there is no fingerprint parser". The §12 example names a step that does not exist; the §6 row lists a component with no binding until "one appears".
- **Fix (rewrite the example; mark the row):** "such as a new sniff version that re-reads every body" (DM §6.2 line 285 gives exactly that case); in §6, "fingerprint (when a candidate appears, DM §6.2)".

- **N5b (same severity):** ARCH §7.4 line 251 now names "the old capture index" in a spec that is "independent of any current implementation" (line 3). PLAN B9 line 197 already owns the fallback. Fix: ARCH says "from the receipts, else a recorded baseline"; the index stays in B9.

### N6. The `name_key` collapse lost its reason — Low — confirmed-from-text

- **Where:** DM §6.7 line 388: "an input's entries sharing a `name_key` keep the first."
- **Mechanism:** The collapse existed because `name_key` was in the PK. The PK is now `(record_sha, parser_version)` and the list can hold both entries; the collapse is a rule with no stated owner. Since `witness_key` hashes `(occasion, name_key)` (§7.11), two same-name witnesses on one panel collide in the model anyway, so keeping the collapse is harmless but unexplained.
- **Fix (delete or justify, one clause):** either drop the collapse and let §7.11 own the collision, or say "so that `witness_key` is unique per occasion".

### N7. New repetition in ARCH §7.4 — Low — confirmed-from-text

- **Where:** line 255 "R2's durability is the accepted guard against decay" and line 257 "R2's own durability guards against hardware loss. A provider-side loss is the accepted risk."
- **Fix (delete):** the clause I asked for at line 255 ends at "the sample is the only content check"; the **Durability** paragraph already says the rest. (~10 words)

### N8. B15 runs on writers B0 has not yet patched — Low — confirmed-from-text

- **Where:** PLAN B15 line 207 "through the existing raw writer, keeping its branch as it is"; PLAN B0 line 172 "today's capture and import writers drop cookies, credential parameters and local paths" is the patch that comes later in the same track; BIND line 149: today's writers "record every response header, `Set-Cookie` included".
- **Mechanism:** B15's first weeks of receipts will carry what B0 removes. B0's scope ("any written since") and its done-when re-scan already cover them, so nothing is lost; the plan should say so in B15, or a reader will think B15 adds dirty receipts after the cleanup.
- **Fix (fold, ~15 words):** "Its receipts before B0's patch are inside B0's scope."

### N9. Worth saying, not a defect

- The "page signals" registry cell (DM §7.1 line 440) is ~90 words in one table cell. Readable, but a sub-list under the table would scan better. Taste.
- The validator's reason for deferring F15 ("whether document IDs reach page URLs") is answered in the text: links carry `link_key` (DM §8.2), `list` has no ID, and "a document's ID is recomputed, not stored" (§8.1). The deferral is safe because the formula only matters at E4; it is not an open question in the docs.
- DM shrank by 114 words. The merges (§6.5/§6.7 two-table layout, the registry cells, the §6.2 populations bullet) added about what the deletions removed. If the owner wants DM shorter, the remaining lever is F14's counts (~250 words), which is a decision already made the other way.

## Keep as is

Everything in the first review's list still holds. Added by this round and sound:

- DM §6 "One row per input" as the one owner of `status`, `error`, `size_limit`, retry and no-row semantics, cited by all four parser tables.
- DM §7.1's rule for when lists share a registry.
- ARCH §7.1's stated reason for B13 and the single named exception to the 412 rule.
- PLAN B15's placement, done-when and successor (B14).
- The fixtures Note with its removal condition.
- PLAN §8's new row for the POST-calendar scope narrowing: a decision not yet made is an uncertainty, not a parked choice.

## Next-change question, revisited

Adding `treaties.parquet` now touches DM §6.4, §7.11, §8.1 and §9, plus one fixture row: five edits, four in one document, with ARCH and the reader untouched. That is the localized answer; the edits delivered it.

## Residual

- BIND's line references were not re-verified (code is out of scope).
- N2's one data check (whether the 313 large `.gz` bodies include PDFs) decides which of two sentences to move; the contradiction itself is in the text either way.
