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
