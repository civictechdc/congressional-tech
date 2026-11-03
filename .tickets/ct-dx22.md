---
id: ct-dx22
status: open
deps: []
links: [ct-qg8e, ct-kthe, ct-j2yo, ct-x78c, ct-5w9u, ct-egg6, ct-66ns, ct-2o4d, ct-67k1]
created: 2026-11-02T00:36:42Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, phase2]
---
# Witnesses attach to the wrong hearing on events with several packages

single_package_meetings (appearance-records-resolved.sql:107-111) checks that a package has one event, not that an event has one package. On 17 events with two or three linked packages, raw MODS titles show v21 chose worse on 3 (100202, 101167, 335827) and tied on 6. Traced to 959c23ee; 86 events are exposed. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.

## Acceptance Criteria

Every event's selected package is justified by a raw record, or no package-sourced witnesses attach; a test covers an event with two packages.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Two-way package-to-meeting rule moves 392 rows on 93 events to package-only; House witness lists get their event from their own document links (187); MODS event-ID links (285 pairs) included. impl-f.

**2026-11-02T13:22:51Z**

2026-11-02 impl-f (r1b-f, 12 commits): package links must hold both ways; MODS eventId counts as a package-to-meeting link (errata prints like 321961 were dropped by the one-package filter); package witness changes mostly ambiguous because MODS states no eventId, 31 unread. Witness keys: 3,921 lost, 3,253 gained (gate 1 cause; release-note-only per ct-ktfe).

**2026-11-02T13:54:36Z**

2026-11-02 (lead): red-f BLOCK: the MODS eventId link attaches the wrong hearing's witnesses (330128, 329130, 335820, 326063); one MODS body per meeting drops the correct print (31 rows); one-to-one links still mis-attach on 31 House meetings (126 rows). Fix: accept eventId only when held date and title agree, rank witnesses per package, and rebuild the raw check on independent raw facts. Sent to impl-f.

**2026-11-02T14:35:28Z**

2026-11-02 (lead): impl-f r1b-f (07b6923f, 24 commits): MODS prints carry held_dates and title; print_meeting_agreement accepts a print only when held that day and at least half the shorter title's words agree; per-print witness ranking. Raw check (independent): print attachments 448 supported, 83 ambiguous, 5 contradicted. Published witness rows 147,888 to 139,077 (about 10k print rows outranked by House XML or Congress.gov lists). red-f2 is checking whether those are duplicates or lost facts.

**2026-11-02T15:10:29Z**

2026-11-02 red-f2 (BLOCK, narrow): all 11 probes agree with raw. The witness drop (10,971 suppressed print rows) is mostly duplicates (10,700 by name, 56 by nickname, 79 on another same-day meeting), but about 53 testifying people are published nowhere and 75 statements are lost, with no disposition. Rule sent to impl-f: precedence per person with superseded_by, unmatched rows published, statements recorded as statements. Linking by witness overlap first, never an eventId veto: 81 wrong links and 160 wrong rejections out of 10,304 pairs.

**2026-11-02T16:11:20Z**

2026-11-02 impl-f r1b-f (rebased on 3e68b62b, engine 5dae611): all red-f2 items fixed. Witness precedence is per person (witness_precedence step; superseded_by column; nickname, spelling, rank and particle matching); letters and Member statements are labelled statements. A print links by shared witnesses (half of the shorter list, at least 2); titles decide only when a side lists none; an eventId never vetoes. Raw check on v21: not_held 430/430; rescheduled 84/86 (2 ambiguous); print attachments 6,909/6,972 (31 matching the old state, 31 a best pick, 1 contradicted: 50139, a seven-day print); red-f2's lost cases 185/192 published (7 are memo/QFR lines). Witness rows: 173,067 published, 141,255 shown, 31,812 superseded, 7,230 statements. red-f3 is checking false-match risk. Frozen inputs: .cache/archive-release/r1b-frozen/.

**2026-11-02T16:28:40Z**

2026-11-02 red-f3 (merge with fixes): 0 false matches among all 31,812 superseded rows, read against raw. Fixes sent to impl-f: the statement labeller mislabels witnesses (at least 21 of 50 sampled testified, including nominees whose counts drop to zero; 702 suspicious rows); matching is brittle (reversed nickname pairs, credential and state tokens as keys, 'Van' as a particle; 8 wrong superseded_by targets); an empty House list created before its hearing (111420) isn't authoritative; a duplicate key at appearance_records.py:1062 (byte-hashed).

**2026-11-02T17:20:32Z**

2026-11-02 impl-f: r1b-f a4fbceb7 and r1b-transcripts edf7a130, rebased onto 0f4711bb; 888 and 897 passed, the only failure being the pin test; statements down from 7,230 to 1,093. Before merge: rebase onto 44785aee, rebuild the frozen after-out, independently re-judge the statements and superseded rows, map each red-f3 item to its test; then a light independent check.

**2026-11-02T17:45:21Z**

2026-11-02 impl-f: r1b-f eeccda09 and r1b-transcripts d8ae25d8 on 44785aee. Independent judge over 1,091 statements: 934 supported by raw, 42 shown by another row, 79 ambiguous, 7 lines not found. Over 32,725 superseded rows: 32,427 supported; the 151 flagged were all read by hand and all are the same person. Red-f3 items (a)-(d) map to tests in e19d5cfa and 07f7809a. Open before merge: 129 names carry GPO's literal footnote marker ('Prepared statement \\1\\'), to be fixed at the root; 55 unlabelled 'for the record' or 'Letter' lines to read in full; 7 lines not found to explain. Integrate blocker: staging video_records fails on unreadable bodies (producer identity keys and reason vs the validator), sent to impl-h as r1b-h3.

**2026-11-02T18:20:46Z**

2026-11-02 green-f4 (light check, r1b-transcripts a437bfd1): MERGE WITH FIXES. (a)-(e) hold in code and data: Vought, Duffy and Al Green are not statements; nicknames are one-way; no \\N\\ markers remain in published fields; 235 prefix-only matches checked with no different people; all 108,506 MODS lines scanned. Remaining, same class: footnote text leaks into names, creating duplicate statement rows (103551, 101897, 105942, 110313, 110380: 11 shown rows), and contents labels survive as names ('Submitted questions' 12, 'Prepared statement' 14; 114537 duplicates Erik Olson). Sent to impl-f to fix before D4 starts.

**2026-11-03T01:00:52Z**

2026-11-02 (Double-Blind Verification): Verified in .cache/archive-release/r1b-frozen/after-out that re-parsing mods with held_dates and title under ct-dx22 resolves 10/10 false CHRG-* transcript collisions (DB-1: 109299, 109300, 109418, 110066, 115519, 115556, 117540, 117541, 335668, 335928) and increases mods witnesses with event_id from 6,225 (publish_v21) to 33,438 (5.4x).

**2026-11-03T02:06:00Z**

2026-11-02 (/etl-workflow Cross-Table Audit — F1): While entity-meetings.sql (meetings.transcripts) and appearance-observations.sql (witnesses) filter CHRG-* package links through package_meeting_links (with fallback WHERE f.package_id IS NULL), model/sql/component-meeting-links.sql:6,13 still joins raw meeting_transcript_links and model/sql/source-annotations-meetings.sql:1-5 still injects raw unnest(p.named_meetings) into document_metadata.meeting_keys -> list.meeting_keys. Consequently, 6,700 rejected (package_id, event_id) edges (including CHRG-117shrg52109 on 330128, CHRG-116shrg37808 on 326063, CHRG-119shrg62654 on 337427, and swapped 100083/100180) still leak into list.meeting_keys. Fix in component-meeting-links.sql and source-annotations-meetings.sql (tracked with ct-j2yo) so list.meeting_keys uses the same vetted package_meeting_links rule as meetings.transcripts.
