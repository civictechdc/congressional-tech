---
id: ct-sfra
status: open
deps: []
links: []
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

