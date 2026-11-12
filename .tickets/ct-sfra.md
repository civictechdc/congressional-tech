---
id: ct-sfra
status: closed
deps: []
links: [ct-gfo7, ct-uz8q, ct-kw85]
created: 2026-11-11T02:06:19Z
type: feature
priority: 2
assignee: mikewolfd
tags: [parser, witnesses, mods, transcripts]
---
# Decide whether a person appeared at a hearing from the transcript's testimony headings

Owner decisions 2026-11-11 (session congress-1, questions dialog): 'Transcripts decide in the rule' (whether a witness or Member appeared, versus only submitted or answered in writing, is read from the hearing transcript's testimony headings, not the index line alone) and 'Next release after this one' (ship the MODS witness-list work without it; build this straight after as its own reviewed release). Design and measurement by the MODS builder in .cache/archive-release/investigations/mods-rebase-20261110/round-7/phase-a: a new small producer transcript_headings with its own pin, reading each transcript once (reusing parse_transcript_html), and a model step after appearance-records-resolved joining about 400 marked MODS rows to the heading table at one pinned version; transcripts exist for 34,595 of 35,020 prints; sample of 300 prints (random.Random(20261111)) plus 11 named: 282 of 311 have capitals STATEMENT/TESTIMONY OF headings; family word plus given initial matches 861 of 999 rows; mixed-case 'Statement of' lines are inserted documents. Refinements: exclude committee members' own headings by roster; trust the line's own word 'Testimony' (13 Members testified with no capitals heading). Expected effect about 22 rows: Gorton stays a witness; 12 Members who only had a prepared statement (e.g. Thomas, Brownback, Levin) become member_statement; Udall, Sessions, Groat, Jeffrey witnesses; Greene, Raben, Beteta, Iovino, Shepard stay statement_for_record. Cost: 2.39 GB gzip read, about 100 s CPU, under 0.5 GiB. Independent check: transcript speaker turns (confirms 97.9% of headings; agrees on 119 of 126 Member rows; cannot see committee members who speak, people at the table who never spoke, two people with one surname, unusual speaker labels). About 950 lines over 12 files.

## Acceptance Criteria

The ~22 rows change as measured and no other row changes unexplained; the producer reads each transcript once and has its own pin; the raw check judges by speaker turns with plants (a testifying Senator typed member_statement; a submission typed witness); an independent reviewer confirms.


## Notes

**2026-11-11T09:48:04Z**

2026-11-11 (session congress-1): also for this ticket: 17 pre-113th-Congress committee members' opening statements stay Member appearances in the coming release because the pinned rosters start at the 113th and the print's own MODS member list omits them; the print's transcript gives 11 of them an 'OPENING STATEMENT OF HON.' heading (the ct-kw85 raw check flags those as leads). Rows: Jeffords (CHRG-107shrg78075 #14); Murphy and Butterfield (CHRG-110hhrg38829); Kingston (CHRG-110hhrg50592); Steve King (CHRG-110hhrg51569); Bright and Mike Rogers (CHRG-111hhrg57926); Conaway (CHRG-112hhrg64659 #8); Fudge and Costa (CHRG-112hhrg68336); Schilling, Crawford and Huelskamp (CHRG-112hhrg74371); Pingree, Schmidt and Conaway (CHRG-112hhrg74372, Conaway #53); Noem (CHRG-112hhrg76176). Source: .cache/archive-release/investigations/member-appearances-20261110/v6/. With transcripts deciding, these become member_statement through the ct-kw85 committee rule; the speaker-turn check stays independent.

**2026-11-11T10:57:59Z**

2026-11-11 (session congress-1): also Dona Abbott (CHRG-109, meeting 108846): her statement_for_record type is read from the cut-off end of a GPO note, but Congress.gov lists her among that meeting's witnesses; it equals the live value, so not a regression; the transcript should decide (seventh MODS review, .cache/archive-release/investigations/mods-rebase-20261110/review-6/r7-signed-verdicts.json).

**2026-11-12T15:57:00Z**

Wave 3 (`claude/ct-wave-3-parsers`): folded `.claude/worktrees/ct-sfra` cleanly onto `claude/ct-wave-3-parsers` (`transcript_headings` lake table, `gpo_headings.py` parser, `model/sql/name-fold.sql` + `witness-transcript-{entries,facts,rows}.sql`, `archive_model.py` / `archive_import_job.py` / `daily.py` wiring, and `scripts/measure/transcript_appearance_raw_check.py` speaker-turn raw check with plants). Verified unit + raw-check tests and end-to-end horizontal slices (`wave3_horizontal_slice_review.md` slices `H3` & `H6`, including `ct-eppo` × `ct-sfra` promoting Carmen Catizone on `CHRG-113hhrg86394` from `statement_for_record` in MODS lake to live attending witness `None` upon matching `STATEMENT OF CARMEN CATIZONE` in `CHRG-113hhrg86394.htm`). Ready for Merge Slot #2 + R2 `transcript_headings` backfill.
