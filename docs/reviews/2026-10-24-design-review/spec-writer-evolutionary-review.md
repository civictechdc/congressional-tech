# Evolutionary review of the adopted specs (commit 39ae52d2)

Mode: audit, read-only. Scope: the three adopted files, read in full.
A = `docs/engine-first-architecture.md`, D = `docs/engine-first-data-model.md`,
P = `docs/plans/simplification-plan-20261024.md`. Line numbers are from the files at 39ae52d2.
No tools were run beyond reading; nothing below is a measurement.

## Verdict

The specs are sound and the owner decisions are stated consistently; no finding below is a contradiction.
The patched-in fixes landed as extra sentences beside the rules they change rather than as changes to the rules, so the same policy now sits in three to seven places (publish order, record role, fingerprint timing, saved-file order, recovery attachment, list order, parser-version completeness).
Two structural strains deserve a reshape, not a trim: the "registries" concept is introduced in a Conformance section and then named inconsistently everywhere else, and the `fingerprint` producer is a lake step that depends on model SQL, which the layering does not admit.
Two genuine gaps: `url_variants` has no consumer, and `alternates` picks "one per format" with no stated tie-break, which threatens byte-determinism.
The plan's E1 is a third copy of the model; it should cite the data model and keep only the plan-specific work.

## Findings, ranked

### 1. Publish-run sequence and input identity are stated four times
- A:474 (§10.4.1 prose), A:540–543 (§12 diagram), D:523 (§8.4 "Inputs and Snapshots", a near-verbatim copy of A §10.4.1), P:248 (F1).
- The input-identity field list is itself duplicated: A:474 and D:510 (the `inputs/*.json` row) carry the same seven items.
- Problem: a change to what the identity covers (for example when `pdf_text` lands) needs four synchronized edits; D §8.4 adds nothing the table row and A §10.4 do not already say.
- Change: make D:510 the owner of the identity's contents; A §10.4.1 keeps the rule (pin once, identity and model from the same snapshots, content not snapshot IDs) and cites D §8.1. Delete D §8.4 except the sentence that belongs nowhere else ("page sizes and row limits are layout settings, not gates"), which moves beside the heap budget in A §11.2. Let the §12 diagram and P F1 carry the order alone.

### 2. `record_role` ownership is split across seven places, with a carve-out bolted on
- A:91 (terminology, with the "every other format takes it from its sniffed format" rule), A:310–311 (§8.3 scope bullets), A:375 (§9.2 item 5), A:380 (§9.2 item 7, third bullet "and no listing pages"), D:190 (column note), D:331–338 (`coalesce(r.record_role, role_from_format)`), D:356–357 (two bullets repeating the block above them), P:201, P:215.
- Problem: the authoritative definition is the SQL at D:331–338. The listing-page carve-out at A:380 is placed under "for HTML, two checks decide" (A:377), making three bullets under a heading that says two; and it is redundant, since `listing` is a record role already excluded by item 5 (A:375). Invariant 22's "no listing page is a real file" (D:597) is likewise implied by invariant 8 (D:580).
- Change: D §7.2 owns the role derivation. A:91 becomes "the classification of a body ([[DATA-MODEL]] §7.2)". Delete A:311 and A:380; fix "two checks" to stand. Delete D:356–357 (they restate D:331–338). Fold the listing clause of invariant 22 into invariant 8 and move "no released `list` is empty" into invariant 17, then delete 22. P:201 and P:215 cite D §7.2 instead of re-listing roles.

### 3. The `fingerprint` producer crosses the lake/model boundary, and the ordering rule is repeated five times
- A:315 ("It evaluates the model's real-file rule over the current lake, before the publish run pins its snapshots"), A:474 ("with `fingerprint` last"), A:541, D:202, D:523, P:202, P:248.
- Problem: §1 and §4 of A say lake rows are a function of raw plus parsers, and the model is SQL over the lake. A lake producer whose work list is the model's `real_files` CTE (which reads registries) inverts that; nothing in the structure says where `real_files` lives. The five repetitions are the symptom: each patch site re-explains the dependency because no section owns it.
- Change: give `real_files` one owner and say what it is: in D §7.2's heading or first line, "a shared CTE over lake tables and registries, used by the `fingerprint` producer (§6.2) and by the model". Then A §8.3 states the scope once ("endpoints with two or more distinct complete real files, per [[DATA-MODEL]] §7.2") and A §12 states the order once (fingerprint, then pin). Delete the sentence at A:315 after "(§10.4.1)", the clause at A:474, and D:202's second sentence; P:202 and P:248 cite A §12.

### 4. Parser-version completeness carries a workaround stated four times
- A:317, D:203, D:573 (invariant 4), P:203.
- Problem: "the model reads the newest complete version" is a dynamic choice that forces the daily run to keep producing the old version while a new one backfills, or the old version silently stops being complete. The fix was patched in as a MUST on the daily run at every site. The simpler rule removes the dynamism: the parser version the model reads is pinned (it is already part of the model/registry version in the input identity, A:474); a backfill is a separate job; the pin moves only when the new version's work list is empty. Then "stays complete" needs no daily-run rule, because the daily run always produces the pinned version.
- Change: reshape A §8.3 "Versions" to the pinned-version rule; invariant 4 becomes "the pinned parser version's work list is empty at the pinned snapshot"; delete D:203 and P:203 (cite A §8.3). This is a hypothesis about intent, not an observed defect; confirm with the owner before applying.

### 5. Registries: introduced in Conformance, named inconsistently, enumerated three ways
- Defined at D:41 (inside §2 Conformance) and referenced from A:59 (also Conformance). Enumerations differ: D:41 lists eleven registries; P:216 lists seven (omits source-record XML roots, listing-page thresholds, format preference order, recheck intervals); the body text still calls them "regular expressions in the SQL" (A:378), "SQL, each entry with a real sample URL" (A:427), "a written mapping" (A:421), "a `(family, interval)` policy table in the SQL" (D:468), "the API-endpoint registry" (D:339), "the generic-stem registry" (D:396).
- Problem: the registry is a design concept (versioned policy tables that are model inputs and part of the input identity), not a conformance clause. Each new list added by a fix was named ad hoc at its site, so a reader cannot tell which lists are registries and therefore versioned.
- Change: move the definition and the full list to a subsection D §7.0 "Registries" (first in Model Derivations), with one sentence in A §9.1: "Lists the rules depend on are registries ([[DATA-MODEL]] §7.0); a registry change is a model version change." Replace every per-site description with "the X registry". P:216 cites D §7.0 instead of enumerating.

### 6. Recovery attachment is stated in six places
- A:401 (§9.3 Listing), A:421 (§9.6), A:447 (§10.1 bullet), D:379 (filenames derivation), D:485 (§7.7 Attachment), D:515 (§8.2), D:591 (invariant 16), P:132, P:223.
- Change: D §7.7 "Attachment" owns it. A §9.6 keeps one sentence and cites it; delete the second sentence of A:401 (keep "a document needs at least one real file or one recovery") and the clause "resolved by the attachment rule (§9.6)" at A:447; D:515 keeps "resolves by the attachment rule (§7.7)" only; invariant 16 keeps its first clause. P:223 cites D §7.7.

### 7. Saved-file total order is stated five times
- A:112 (terminology), A:405 (§9.4), D:406–410, D:582 (invariant 10), P:228.
- Change: D §7.4 owns it. A:112 becomes "the file a document's page links ([[DATA-MODEL]] §7.4)"; A:405 states "PDF first, then newest, then body hash" in words and cites D; invariant 10 may keep the order because it is the test oracle; P:228 cites D §7.4.

### 8. `list` order is stated five times
- A:437 (table), A:411 (§9.4 third bullet), A:446 (§10.1 "Editions sit together"), D:500, D:589 (invariant 14).
- Change: D §8.1 owns it; A keeps the table cell and the one-line reason at A:446; delete A:411's first sentence (keep the two sentences about undated and import-only files, which are the actual rule).

### 9. `alternates` has no tie-break within a format
- D:411–412 "real files in formats other than the saved file's, one per format: … in format-preference order"; A:405 "one per format".
- Problem: a document can hold several real files of one format (same-body and same-text edges, for example a re-packaged PDF). Which one is the alternate is unstated, so two runs can emit different bytes, which §10.3 forbids.
- Change: "one per format, chosen by the saved-file order within that format (first_fetched desc nulls last, body_sha)". One line at D:411; invariant 10 or a new clause in invariant 14 tests it.

### 10. `url_variants` has no consumer
- D:133 says it is read by "endpoint canonicalization, beyond what `url_key` catches"; D:325 "adds accepted variants beyond what normalization catches". No derivation in D §7 uses it: `url_key` (D:301–318), endpoint matching (D:321), `filenames` and edges never mention it.
- Problem: a provenance kind the model is said to read but does not. Either an omitted rule or a dead record kind.
- Change: specify where it applies, most plausibly as a final step of `url_key` ("then map `variant_url` to `canonical_url` from provenance `url_variants`"), and add it to the input identity (the provenance digest already covers it). If no rule is intended, delete the row at D:133 and the bullet at D:325.

### 11. Completion rows use two mechanisms for one fact
- D:143 introduces `is_completion boolean`; D:237, D:264, D:284 each also give PK sentinel values (`link_index = -1`, `congress = 0, system_code = ''`, `chamber = '', event_id = 0`); D:242 adds "null only in a completion row"; D:296 "excluded from every input"; D:469 reads them for `links_scanned`.
- Problem: boolean plus sentinel is flag accumulation; readers must know both, and a third table would need both again.
- Change: one rule in the §6 header: a completion row is identified by `is_completion = true`; its PK columns take the type's zero value (`-1` for an index, `0` for an integer key, `''` for a string) and its other columns are null. Delete the per-table sentinels at D:237, D:264, D:284 and D:242's clause.

### 12. The release-rerun HEAD is a carve-out stated twice
- A:486 ("with one HEAD of that object's ETag; this is the only HEAD of an immutable file the system makes") and A:564 (capability 5, "except the one HEAD that verifies a 412 on a release rerun").
- Change: keep the rule at A §10.4.4 without the "only HEAD the system makes" assertion (it is not testable as written and reads defensive); capability 5 says "except as §10.4.4 allows".

### 13. `first_run` has no consumer
- D:377 defines `first_run` with a total order; P:224 lists it among "earliest" picks. Nothing in D §7.4, §8 or the invariants reads it (date_kind now derives from `in_archive_since`, D:416–418).
- Change: name the consumer (if it is the "import day defined by run" check, say so in D §7.4) or delete the column and its mention at P:224.

### 14. `date_kind` is a stored derivable
- D:416–418 defines `date_kind` exactly as a function of `first_captured` and `in_archive_since` being null; both appear beside it in `documents` (D:455) and in the `detail` fold (D:505).
- Problem: Principle 7 (A:170) says nothing derivable is stored, except in browser files where shape follows the reader. `list` qualifies; `documents` and the `detail` fold do not.
- Change: keep `date_kind` in `list` only; drop it from the `documents` column list and the `detail` fold. Low priority.

### 15. Terminology entries carry rules
- A:100 (placeholder: *k* = 100 and "It connects nothing"), A:112 (saved-file order), A:114–115 (import run and its label), A:117–118 (document-date precedence), A:144–145 (pointer fields).
- Problem: a definition that restates a rule is a second owner of that rule; four of these five were edited in by the fixes and now diverge in detail from their section (A:100 vs A:397 vs D:360; A:145 vs A:498 vs D:511).
- Change: trim each to identity plus a section cross-reference.

### 16. Plan E1 is a third copy of the model
- P:214–235: twenty-two bullets restating the real-file rule, registries, recovery attachment, saved-file order, document date, ID serialization, edge set, review semantics and meeting joins, all of which D §7 owns.
- Change: E1 says "every derivation in [[DATA-MODEL]] §7 and every registry in §7.0, as SQL, with the invariants of §10 as its tests", and keeps only what is plan-specific: start from the broader page-shape list and sample the ~27k between the lists; a sample test per registry entry; the adversarial fixtures (already in S, P:109, so cite S). Same for P:201 (D2 restates the `readings` columns; cite D §6.2) and P:147 (B2 restates A §7.1–7.2 in one 120-word sentence; a cross-reference and the three plan-specific actions suffice).

### 17. A §16.2 duplicates plan §5
- A:614–620 lists the five pre-build measurements; P:86–103 (M1, M2) specifies them. A:349 also says the plan confirms manifest growth.
- Change: A §16.2 becomes one sentence: "[[IMPLEMENTATION-PLAN]] §5 measures the engine on the smallest runner before the lake and model are built on." Delete the list.

### 18. Numbers that no longer size a design (owner decision: only sizing numbers stay)
- D:213 "25 URLs in 7 lists in house-naming 3.2.7" (version-specific; the rule needs only "exact mirror URL").
- A:399 and D:429 "1.26M components, largest 456 source files" (duplicated; pre-rule history).
- A:184 and D:428 the 454k/98k/10k/1k breakdown (duplicated; A §5 should hold it once if kept).
- A:240 "The 201 bodies"; A:382 and D:361 "about 34,000"; D:430 "368,748 have no capture date".
- A:448 and A:450 (list size with and without IDs; hex vs binary MB): rationale for decided rules, not sizes to design for.
- Change: keep each once where it sizes something (A §5 for scale, D §8.1 for file sizes); delete the rest.

## Owner decisions: consistency check

All stated consistently; no contradictions found.
- Editions stay apart: A:394, D:399, D:595 (inv. 20), P:232. Consistent.
- ZIP members by own path: A:382, D:361, P:233. Consistent.
- Every facet value kept: D:217, A:437. Consistent.
- Listing pages are not documents: A:375, A:380, D:337, D:357, D:597. Consistent in substance (see finding 2 for the redundant statements).
- Rendition group needs different formats, one per format: A:394, D:397–398, D:596 (inv. 21), P:227. Consistent. Finding 9 is a gap in the alternates rule, not an inconsistency.
- Recovery with no single document keeps its own page: A:401, A:421, D:485, D:515, P:223. Consistent (finding 6 is duplication only).
- Document date (filename → contents → meeting) separate from capture date: A:117–118, A:409, D:419–421, D:582. Consistent. Column rename `document_date` → `filename_date` in D §6.3 is carried through A:416 and P:205.
- Review hide leaves a note; duplicate merges: A:423, D:491–492, D:595. Consistent.
- Raw on R2 only: A:274. Speed targets after measuring: A:514, P:136. No schedule: P throughout. Consistent.
- Only sizing numbers stay: see finding 18.

One wording inconsistency, not a decision conflict: the labeling rubric at P:110 says "two files are one document only when they are the same text in different formats", but same-body and same-text edges (A:392–393) also make one document from identical bytes or the same text in the same format. Reword to "the same content: identical bytes, the same text at one address, or renditions of one text in different formats".

## Bolted-on wording (style check against the original brief)

Sentences that read as patches appended to a paragraph rather than integrated into it:
- A:232 last clause ("; the `sniff` parser decompresses gzip-stored bodies before reading their first bytes") — belongs in §8.3's sniff bullet, where D:201 already says it.
- A:268 "the lock, not the token, is what stops deletion and overwrite (§14)" — §14 says it; keep one.
- A:315 second-to-last sentence; A:317 "and while a newer version backfills …" (findings 3, 4).
- A:325 "The producer applies the effective-filename rule itself, as a lake-level rule." — duplicates D:228; one of the two.
- A:380 third bullet under a "two checks" heading (finding 2).
- A:399 last sentence ("The model reports the largest components by edge kind; before the real-file rule …").
- A:486 "this is the only HEAD of an immutable file the system makes" (finding 12).
- A:510 last sentence (33,479 occurrences; D:507 has it).
- A:514 last sentence ("The first measurement uses a release with about twice the target row count") — plan content inside a spec; P:117 and P:136 already say it.
- D:195 "now" in "HTML and XML metadata or a dated heading now; PDF text once `pdf_text` exists" — a forward note; say "from HTML and XML; from `pdf_text` when it exists".
- D:229 "Superseded versions are kept; that cost is accepted." and P:205 "superseded catalog versions are kept" — one of the two.
- D:380 "ID serialization" bullet repeats the `source_id` table row above it; merge into the row.
- D:597 invariant 22 (two unrelated facts; finding 2).
- P:90 "The remote write cap" paragraph — a review finding pasted into M1 with its reasoning ("with no recorded reason", "weakens dictionary encoding"); keep the action ("measure the 2 MiB file cap and 2,048-row group cap on the scratch table; keep them only if they measurably help") and drop the argument.
- P:110 rubric sentence (see consistency note above).
- P:138 "Opening older gzip PDFs through their `.pdf` copies waits for B13." — the dependency is already at P:130 and P:146.

No revision notes, review acknowledgments, "Note:" asides or owner-decision tags remain. Terminology is defined once (D §3 defers to A §3), which is an improvement over the pre-adoption draft.

## What was left alone, deliberately

- The five conformance classes (A:51–57) are not referenced by any normative statement afterwards, but they map cleanly onto sections and cost one paragraph; not worth removing unless they also stay unused after the next revision.
- `meeting_keys` as `chamber:event_id` strings in `list` beside `meeting_refs` structs in `detail` is two shapes for one fact, held consistent by invariant 13. That is the stated browser-file exception (A:170) working as intended.
- The dates model (`first_captured`, `in_archive_since`, `document_date`, `document_date_source`) is more columns than before but each is a distinct fact; only `date_kind` is derivable (finding 14).

## Coverage and evidence

Read: all 644 + 621 + 297 lines at 39ae52d2 and the commit message. Not run: any script, test or build (the task is a document audit). Findings 1–3, 5–8, 11, 12, 15–18 are observed duplication or placement; 4 and 10 are inferred design intent and should be confirmed with the owner; 9 and 13 are observed gaps (unstated tie-break; unreferenced column).
