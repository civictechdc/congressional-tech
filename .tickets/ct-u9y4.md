---
id: ct-u9y4
status: in_progress
deps: []
links: []
created: 2026-11-10T05:08:06Z
type: bug
priority: 1
assignee: mikewolfd
tags: [model, recoveries, identity]
---
# Recovered documents with the same file name are fused: 215 documents hold several different recovered bodies and show one

Found 2026-11-10 by the all-live-link-keys check on release candidate 619db5f9 (.cache/archive-release/release-20261110/causes-2/orchestrator-checks/all-live-link-keys.md). Link key cae8e4ea34ec603a, 'Bowman Testimony.pdf': the live release shows Terry Bowman's testimony to House Oversight of 2012-02-08 (15 pages, 639,987 bytes, oversightdemocrats.house.gov); the candidate shows his testimony to the Education and Workforce HELP subcommittee of 2018-04-26 (12 pages, 342,509 bytes, democrats-edworkforce.house.gov). Two different documents are one row because both are recovered under one file name; which is shown flipped when one was fetched live on 2026-11-08. The candidate's recoveries.parquet has 215 documents with two or more different recovered bodies, 187 from different hosts (row 1472: augustine.pdf from a 2004 and a 2007 Science hearing). How many are truly different documents is unmeasured. An existing class on the live release, not caused by ct-h3jb or ct-f7hp; raw holds every body.

## Acceptance Criteria

Every multi-body recovery document is either shown to be one document (same text) or split, with counts. Bowman 2012 and 2018 are two rows. A release gate or model invariant flags a recovery document whose bodies differ in text.


## Notes

**2026-11-10T13:16:36Z**

Owner decision 2026-11-10: correct the records. Mark the wrong acceptances in the recovery records and re-record each file under its own address (option 1 with re-recording), so each hidden file becomes its own document.

**2026-11-10T13:27:30Z**

2026-11-10 status: the model rule (a recovered copy moves its link only when it is the copy the link shows) is on claude/ct-next-release (4bd50c6d..f8192a6a) and separates 18 of the 56 unrelated fusions. For the remaining 38 the owner chose record corrections; a builder is preparing them and proving them on a local copy in wt/ct-u9y4-records (report: .cache/archive-release/investigations/recovery-records-20261110/README.md). No raw write happens until the orchestrator has read that report. Left: the correction write, full model build, review, release.
**2026-11-10T08:53:20Z**

Measured and partly fixed on branch claude/ct-recovery-identity (local: tests 232f4341, fix bce3cee9; not pushed). Evidence, scripts and the per-document table: `.cache/archive-release/investigations/recovery-identity-20261110/` (README.md first).

**What joins them.** Not the file name in the model: 209 of the 215 are ONE dead address that was accepted twice, once by the `filename-recovery-all-20261015` run and once by `webharvest-import-839-20261015` (no category, no decision record). Every recovery row of a link belongs to that link's document (data model 7.8), so both files sit on one row and the first in the recovery order is shown.

**Measurement (text, not names).** 414 distinct bodies; 411 fetched from the public origin and hash-checked, text by PyMuPDF and an HTML parser, compared by 5-word shingles, then read by hand where not clear-cut.

| class | documents |
|---|---:|
| different documents (unrelated; a same-name file from another hearing or committee) | 56 |
| a page capture beside the file it carried, or an official record offered as containing it (81 veterans.house.gov, 2 others) | 83 |
| same document, other edition, format or part | 18 |
| same content (equal or near-equal text) | 45 |
| cannot tell (10 scans with no text layer, 3 recordings over 80 MB not fetched) | 13 |

All 56 different-document rows hold a copy whose address shares only the file name with the dead address, all with match basis `user_accepted_url_variant`; 53 of them came from another host. By host: democrats-science 50 different + 3 scans; veterans 81 page-plus-file; waysandmeans 40 same, 4 editions, 1 different; thomas.loc.gov 7 multi-part reports.

**Wider population.** 3,696 documents hold ONE recovered body whose copy came from another host under the same file name (3,062 with the same directory tail, 634 file name only; 965 beside a live file). Fixed-seed sample of 30: 25 agree with what the dead address names, 0 different, 5 cannot tell (scans). Reading 65 of the 67 bodies of the riskiest stratum (file name only, other host, `user_accepted_url_variant`; 2 over 80 MB skipped): 1 likely wrong (row 289232, Oversight Democrats `Kelly.pdf` answered by a 2009 Science Committee FERC testimony), 4 scans, the rest consistent.

**Cannot see.** Scans and recordings; a single-body row has nothing to compare against but the address's own words, so a wrong file with a plausible date passes; "same content" is judged on extracted text, so a changed figure or signature page is invisible; 30 of 3,696 leaves up to about 10% undetected at 95%.

**Rule implemented.** A recovered copy that equals a live body used to move its dead link into that live document, whichever of the link's copies it was. Now the link moves only through the copy its own row would show (first in the recovery order), or through another of its copies with the same text fingerprint. The link's key then always reaches a row holding the file the link shows, whatever else is fetched live. Owner: `model/sql/provenance-recovered-copy-links.sql`.

Run through the pinned engine on the published release's rows (`ri_10_native.out`): the old SQL reproduces the release (4,497 moved links, each URL key on the published row); the new SQL moves 4,469 and adds none. Of the 28 that stop moving, 3 see no change (the dead address is itself fetched live on that row) and 25 links return to rows of their own, out of 23 live rows:

- 18 rows, 19 links: different documents, Bowman among them (2012 on the link's row with key cae8e4ea34ec603a, 2018 on the live row with key 75e859b7ff421c86).
- 2 rows (334942, 335064): the same text in PDF copies one byte apart. The model has no PDF fingerprint, so it cannot tell these from Bowman. They rejoin by themselves once PDF text fingerprints reach `body_fingerprints`.
- 2 rows (25362, 25615): a House report's PDF and its congress.gov page. 1 row, 2 links (234486): scans.
- All 25 URL keys still reach the file they answer today (it stays a recovery on the link's row), so the gate's link rule passes; body keys do not move; lookup keys follow the link. Per-link list: `rule-effect-after.csv`.
- The 25 dead addresses leave `sources` (a recovery-only row lists none): the gate will report them as "URLs gone" and need a recorded cause.

**Alternatives on the same rows** (`ri_12_alternatives.py`): "move only if every copy agrees" also un-merges 2 more same-content rows and 3 veterans rows for no extra correct split. "A file-name-only copy is not attached" catches all 56 but would strip the only recovery from 951 single-body rows that the sample says are right. "Every unproven recovered file is its own row" splits 184 rows (14 of them same content) and needs 194 new rows with a key of a new kind.

**Not fixed, needs an owner decision.** The rule only stops a live capture from pulling a link into another document. A link's own row still holds every file accepted for it and shows one. 38 rows still hide an unrelated document: 34 recovery-only, and 4 (298088, 302779, 348262, 356005) where the link's only recovered copy is the wrong file, so the link still sits in the unrelated live document. The 83 page-plus-file rows, the editions and the unknowns are unchanged. Options:
1. Reject the wrong acceptances in the recovery records (56 known, 10 scans to look at). Right at the source, but each rejected file leaves the release unless it is re-recorded under its own address; 34 are published nowhere else.
2. Give each unproven recovered file of a dead address its own row. Needs a new key for the second row (a URL key is taken, and a recovery-only body may not be a link key) and wrongly splits same-content PDFs until their text is read.
3. Decide whether a page capture and the file it carried (81 veterans rows) are one row or two.
Also open: whether a recovery-only row should list its dead address in `sources` (6,169 rows list none today).

**A full model build must confirm:** Bowman is two rows with the keys above; the 25 links of `rule-effect-after.csv` each have a row whose saved file is the "own row shows" body and whose recoveries include the "live row shows" body; no link key, lookup key or body key is missing and `link_rule` is ok; `recovery_documents_with_several_files` reports about 217 (same_text 31, text_differs 25, text_unread about 161); `unaccounted_merged_signal` is 0; the 25 "URLs gone" and 25 new recovery-only rows get a recorded cause. No model build was run.

**2026-11-10T13:48:10Z**

Correction prepared and proved locally (claude/ct-u9y4-records; nothing written to raw). Evidence, staged records and commands: .cache/archive-release/investigations/recovery-records-20261110/ (README.md first).

**Mechanism.** No code change. A provenance recoveries record with kind rejected drops one (dead address, body) acceptance; a file goes under another address through a new retained_import receipt plus its decision (corpus_recovery.reconcile stage/import). Both tools exist; four tool files are identical to main.

**Second reading** (Poppler, lxml, 3-gram and cosine, Tesseract OCR): 66 rows hold an unrelated file, the earlier 56 plus all 10 scans (OCR settles every scan). Every wrong acceptance came from webharvest-import-839-20261015. The only disagreement is the 10 scans (earlier: cannot tell). The 3 recordings stay undecided; the page-plus-file rows, editions and same-content rows are unchanged.

**Correction set.** 69 rejections (one stage object, provenance/recoveries/20261110T210000+0000.jsonl). 58 distinct wrong files: 23 are live, and 11 are already the recovery of their own address. The other 24 are re-recorded under the harvest receipt's recorded address: 24 receipts plus one stage object, provenance/recoveries/20261110T210001+0000.jsonl. That makes 26 create-only objects; write the re-records first. An undo stage script is ready.

**Proof** (model recovery SQL through the pinned engine on the release's 12,796 recovery rows; the rebuild of the release matches except 165 ZIP-wrapper or unrelated rows). Base to corrected:
- the 69 pairs are removed and the 24 rows added, each alone on a new document;
- 5 dead links leave the 4 live wrong-file rows (298088 x2, 302779, 348262, 356005) for rows of their own;
- 4 documents switch from the wrong file to their own hearing print;
- 0 link keys lost, 9 answer another file (all corrected), 0 files leave the release, 0 reviews touched;
- under main's rule the result is the same on all 93 corrected links;
- planted errors are flagged.

**Open for the orchestrator:** run the writes (README part 3) outside a nightly. The gate then needs cause records for the 24 new rows and the 9 changed keys.

**2026-11-10T14:23:27Z**

Correction revised after the independent review (.cache/archive-release/investigations/recovery-records-20261110/review/REVIEW.md); README.md in that folder is current. This note supersedes the numbers in the previous note.

**Baseline.** The previous note measured against rule 65453a82, which is not published. Against the published release 619db5f9e08e, measured per link key (effect-A.csv):
- 30 dead links answer a different file;
- 26 dead links leave 23 live rows (row 1472 is one);
- 4 rows change their shown file in place;
- 50 new rows (26 dead links plus 24 re-recorded files);
- recoveries go from 12,632 to 12,587;
- 0 keys lost, 0 files leave.

Against the stack (effect-B.csv) the numbers are 9, 5 from 4 rows, 4, and 29 new rows. Both baselines end in the same state for all 93 keys. Do not use 9, 5 or 4 in a cause record when the gate compares against 619db5f9e08e.

**Write.** 25 objects, down from 26:
- 24 receipts (receipts alone give accepted rows, the same as import 839's undecided rows);
- 1 provenance object, provenance/recoveries/20261110T130500+0000.jsonl: 69 rejections, 57,003 bytes, sha256 963463ab. decided_at is the owner's decision time, 13:05Z, and the notes are plain evidence statements.

Write from a clean worktree at origin/main; the tools are byte-identical there.

**Before the write.** A model-only build with the 24 capture rows and 24 filename readings appended to the pinned snapshots (scripts/rr_20_captures_input.py). Without the readings the model refuses with missing_filenames = 24. Then check the build against effect-A.csv with scripts/rr_21_check_build.py.

**Undo.** It restores what readers see, not the rows: the 69 rows return with a new id and a decision id.

**2026-11-10T18:57:55Z**

2026-11-10 18:57Z THE CORRECTION IS WRITTEN to the raw store (owner approval 'Go all the way if it matches'; writer commit aef93461, on origin/main): 24 receipts receipts/documents/2026-11-10/recovery-20261110T185720Z-07ed0bdf53ee-reconciled-<sha256>.jsonl.gz (run recovery-20261110T185720Z-07ed0bdf53ee; keys in investigations/recovery-records-20261110/correction/written-receipt-keys.txt) and one provenance object provenance/recoveries/20261110T130500+0000.jsonl (69 rejections). Read-only checks before and after both print ok: true (.cache/archive-release/release-20261110b/runs/). Nothing replaced. The publisher run that reads them follows.

**2026-11-10T20:38:25Z**

2026-11-10 PARTLY SHIPPED, left open. Checked on published release 77673bfb8fcf (2026-11-10T20:27:52Z) against 619db5f9e08e with DuckDB on the published tables, not on notes. Bowman is two rows: cae8e4ea34ec603a -> row 67037 (639,987 bytes), 75e859b7ff421c86 -> row 67036 (342,509 bytes). The 69 rejections and 24 re-recorded files shipped (cause record: 24 added rows, recoveries -45, 30 link and 38 lookup keys as named corrections). Documents still holding 2 or more distinct recovered bodies: 149 (model query recovery_documents_with_several_files: same_text 31, text_differs 25, text_unread 93). Matched by body to the 215-row classification (investigations/recovery-identity-20261110/multi-body-classification.csv): 83 a page capture beside the file it carried (veterans and 2 others), 45 same content, 18 same document in another edition or part, 3 cannot tell (recordings over 80 MB, never fetched), 0 different documents (was 56, plus 10 scans OCR showed were different). So no unrelated documents are fused in the release any more. In scope by this ticket's acceptance ('every multi-body recovery document is shown to be one document or split', and 'a gate or invariant flags' differing text), and still to do: (1) owner choice on the 83 page-plus-file rows: one row or two (option 3 of the 08:53Z note); (2) accept the 18 editions as one document or split them; (3) read the 3 recordings; (4) recovery_documents_with_several_files only reports: 25 text_differs ship without any refusal. Make it an invariant with a reviewed list of accepted rows, or record why a report is enough. Also still open: whether a recovery-only row lists its dead address in sources.

**2026-11-11T14:44:47Z**

validated 2026-11-11, left open: nothing changed since the 2026-11-10 20:38Z note (no commit names ct-u9y4 since). Bowman is two rows in 77673bfb8fcf and no unrelated documents are fused, so the core defect is fixed; what remains are decisions and one guard: (1) the owner's choice on the 83 page-plus-file rows (one row or two), (2) the 18 editions (one document or split), (3) read the 3 recordings, (4) recovery_documents_with_several_files is a report only (25 text_differs ship without a refusal): make it an invariant with a reviewed list, or record why a report is enough.

**2026-11-11T16:09:08Z**

2026-11-11 BUILT on branch claude/ct-doc-roles-2 (local; tests 3d98c0f2, fix 90b61c03; not pushed, not model-built). Owner decisions 2026-11-11: "One document, file shown" (83) and "Split into separate documents" (18). Report: .cache/archive-release/investigations/doc-roles-2-20261111/NOTES.md.

One reviewed registry, model/registries/recovered-file-roles.json, per (dead link, recovered body) like a provenance decision: source_page 81, edition 18, same_document 41, undecided 6.
- source_page (the 81 veterans pages): the capture of the dead page itself leaves recoveries; the document shows the file; the dead address is an unsaved sources row with its listing page (ct-m878 shape). The other 2 of the 83 (armedservices statement + print, science roll-call sheets) have no web page and already show the file: same_document.
- edition: each other edition moves to the row holding that body as a real file, else a new recovery-only row keyed by its body; the link keeps its URL key and its file; the dead address's lookup key names both. 17 of 18 split (15 new rows, 1 to live hearing row 82476). The 18th (frwebgate CHRG-111hhrg61759) is the GovInfo PDF and its own HTML, already one document by the rendition rule: same_document.
- Item 4 settled as a refusing invariant, recovered_file_invariants: several_files_unreviewed (several recovered files whose text is unread or differs, any unreviewed) and links_without_a_file. The report stays as metadata; recovered_file_roles_unused counts stale entries. Reason: the Bowman fusions were text_unread PDFs a report counted and nobody read; recovery rows come only from deliberate imports, so the refusal lands on the importer.
- Item 3 (the 3 recordings): undecided, out of scope.

Predicted on 77673bfb8fcf (DuckDB, dr2_30..34): recoveries -81, 18 rows move; +15 documents; +78 sources; 27 documents show the file instead of the page; +15 body keys, no key lost; report after same_text 31 / text_differs 4 / text_unread 16, all reviewed; invariants 0/0.
Owner should know before release: the 27 change title (20 to the hearing's title, 7 to none, so the filename shows; the page title is the ct-m878 question on ct-egoo); the gate's link rule lists 27 link and 27 lookup keys answering another file (dr2-33-changed-*.csv) that need a cause record; edition body b3b270 (House Report 107-539 pt 1) becomes a new row beside row 321977 that already shows it under another dead link.

Tests (focused, worktree runner): fail before (4 failed), pass after (10 passed), plus the focused files listed in the report. A full model build must confirm the numbers above.

**2026-11-11T16:52:12Z**

2026-11-11 owner answers applied on claude/ct-doc-roles-2 (tests cca2425b, fix see branch log): "Keep the page's old title". A document that showed its dead page (the page first in the recovery order) keeps the page's title on the file. On 77673bfb8fcf exactly the 27 are affected and all keep their published title (dr2-34-title-changes.csv: published / without the rule / with it); without it 20 took the hearing record's title and 7 had none. Focused files all pass (focused/SUMMARY.txt in the report folder).
Duplicate the split makes: edition body b3b270 (House Report 107-539 pt 1) becomes its own document while row 321977 (views.pdf, another dead link, shown through the same report) already shows those bytes. No existing rule joins them: the same-body edge and the recovered-copy move need a real file, and a duplicate_of review cannot name the edition's body key (initial keys precede the split). Same class as today's 191 recovered files each shown by 2+ recovery-only rows (446 rows); not folded here.
