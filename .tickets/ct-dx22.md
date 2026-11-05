---
id: ct-dx22
status: closed
deps: []
links: [ct-qg8e, ct-kthe, ct-j2yo, ct-x78c, ct-5w9u, ct-egg6, ct-66ns, ct-2o4d, ct-67k1, ct-lx67]
created: 2026-11-02T00:36:42Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, phase2]
---

# Keep witnesses off a hearing date their source does not support

People researching a hearing should see a witness on an individual sitting only when the evidence supports that date. In `e145d24c389e`, the archive puts Thomas L. Farmer and Raymond J. Reese from `CHRG-112hhrg72238` on June 2, 2011 (event `100098`). The retained hearing print places both under July 12 (event `100099`).

## Root cause (2026-11-05)

The exact retained GovInfo metadata (MODS) and parsed appearance record describe a print with two held dates and carry no event for either witness. The previous join in `model/sql/appearance-observations.sql` used a print-to-meeting link to date each appearance without evidence for the individual assignment. The published transcript list showed the package on June 2 only among the two checked events. The print independently establishes the July sitting. Admission of a July edge in the private agreement data remains unverified.

## Implementation and remaining checks

The first-wave merge `18049548` includes the model fix. When a hearing print covers more than one date, the archive keeps the print’s undated witness list under its package and preserves separately supported sitting assignments and print links.

The bounded native check moved all 10 appearances from the exact `CHRG-112hhrg72238` metadata off June 2 and kept the supported June print link. The July sitting has a separate retained jacket (`72257`). Eight focused checks passed, including controls for a single sitting and two supported print links.

After the build hold clears, the release coordinator will trace the named July link separately and verify package scope, document links and the disposition of the former Farmer and Reese keys `c91a7472a2a51731` and `9fb4f01557e8b8b6`. Record appearance key and witness-link changes under gate 1 and document link continuity under gate 2. [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md)

## Acceptance Criteria

- In the two-date fixture, neither named witness is assigned to June 2 solely through the print. An independently supported June witness stays there. An unresolved appearance has `event_id=NULL` and remains visible at package scope without being copied to either sitting.
- The two-date control retains both legitimate print links when the links have supporting evidence. For the named package, preserve supported links and trace the missing public July link through the existing print agreement separately. Require individual evidence before using either link as a witness date.
- Keep the two-package and same-day collision controls. Preserve source occurrences, locators, panels, document links and literal affiliations.
- Account for any changed occurrence keys and document-witness links in the existing gate 1 cause records. Preserve public document link continuity under its separate gate.
- Verify the named records against the retained source, owning model output and installed selected release. Record the affected scope, relevant pins and candidate qualification.

## Coordination and evidence

The independently read contents are on PDF page 3, printed page III. The witness keys in the checked release are `c91a7472a2a51731` and `9fb4f01557e8b8b6`. [Root-cause analysis](../docs/plans/production-mvp-root-causes-20261105.md) · [Earlier release comparison](../docs/measurements/release-diff-c94bfedc-448651e7-20261101.md)

Share the retained print with the affiliation work and coordinate package-association meaning with the recording work. Each repair can proceed independently. [Affiliation parsing](ct-lx67.md) · [Recording scope](ct-j78x.md)

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

**2026-11-03T12:48:59Z**

Implemented and verified on r3-mcp / release-train (4d583687): removed unvetted CHRG-* named_meetings from list.meeting_keys in document-normalized.sql, document-recovery-normalized.sql, and source-annotations-meetings.sql so list.meeting_keys agrees 100% with vetted package_meeting_links in detail.meetings.

**2026-11-04T15:07:16Z**

2026-11-04 confirmed recurrence: a combined print's witnesses receive the wrong individual sitting date. Reopened on fresh live/PDF/Parquet evidence, preserving the earlier multi-package-collision fixes and history. Live release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; checkout inspected separately at 730a2d8e0c55880fc058d13cc74d265fc315f41f. This is ticket-only follow-up to chaos-personas-20261104; no repair, tests, source regeneration or publication was performed. Fresh runtime schema is retained in .cache/archive-release/chaos-personas-20261104/ticket-accountability/runtime-check.json.

Bounded reproduction: package CHRG-112hhrg72238, document reference release=e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd, link_key=19397c330522ea96. SHA256-verified 524,902-byte PDF body is 19397c330522ea962c88017f1e8bf496effc66fbaf306924f5fbb950d7cf11c8. Its physical PDF page 3 / printed contents III places Thomas L. Farmer and Raymond J. Reese under TUESDAY, JULY 12, 2011. The release instead publishes both witness keys c91a7472a2a51731 (Farmer) and 9fb4f01557e8b8b6 (Reese) with event_id=100098, whose meeting_date is 2011-06-02. The correct July sitting is event_id=100099. Both dates are legitimately covered by this print; a document-to-meeting link for both is not a per-witness date assertion.

Useful read-only reproduction: SELECT w.witness_key,w.name,w.package_id,w.event_id,m.meeting_date FROM witnesses w LEFT JOIN meetings m USING(event_id) WHERE w.witness_key IN ('c91a7472a2a51731','9fb4f01557e8b8b6'); then independently read the retained PDF contents page. Exact MCP requests/responses are accountability/calls.jsonl calls 20,21,37,40; independent Parquet values in independent-table-audit.json; source-case-audit.json contains the separate PDF reading and positive/planted-wrong-date controls. All are under .cache/archive-release/chaos-personas-20261104/. Only these two witnesses were individually adjudicated; no corpus-wide error count is asserted.

Current owning source path at the inspected revision: package-meeting-links.sql permits each agreeing held day, print-meeting-agreement.sql compares whole-print held_dates/witness lists/title, and appearance-observations.sql:175-198 assigns a MODS appearance's event/occasion through the package-level join. The MODS extraction (appearance_records.py:1088-1148) records package held_dates/title but not each witness's sitting. This source inspection identifies the missing distinction; exact raw MODS-to-live producer replay was not performed. Merely broadening a package-to-meeting join could copy the whole witness list to both dates and make the error larger.

Additional smallest acceptance for this recurrence: (1) a fixed two-date print fixture proves Farmer/Reese belong to July 12 and a June-only witness stays in June; keep the print linked to both legitimate dates; (2) never copy every package witness onto every held date; if the source cannot identify an individual sitting, preserve the appearance as package-only/explicitly unresolved instead of fabricating a date; (3) retain the existing multi-package and same-day collision controls; (4) document affected records and required parser/model pins, qualify and publish the corrected output, and read these named witnesses back through the installed selected release before closure. Local fixture success alone does not repair live e4538f00. Date assignment and organization parsing are separate defects.

**2026-11-04T15:23:03Z**

Coordinated producer plan frozen 2026-11-04: docs/plans/congress-explorer-root-cause-remediation-20261104.md. This addendum refines remaining work without rewriting prior evidence. Live evidence remains release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; source inspected at 730a2d8e0c55880fc058d13cc74d265fc315f41f. Planning/ticket update only: no implementation, tests, prepare, acquisition, data changes or publication.

Owner: appearance model binding in model/sql/appearance-observations.sql:171-198, using retained MODS held_dates/title and the existing vetted package agreement. A multi-date print's package-wide witness list stays package-scoped with event_id=NULL absent source evidence for the individual sitting, even if only one package-to-meeting edge currently matches. Keep the print's legitimate multiple meeting links. Do not add a per-day transcript parser or copy the whole witness list onto every held date. This narrows the prior addendum: the independently known July date is the counterexample; reconstruction of that date is not required where the maintained record has only package scope. Phase-2 annex section 4.2 permits unresolved package-only MODS appearances; sections 4.6-4.7 preserve source occurrences and explicit unknowns.

Add decisive cases to maintained owning/native tests: the retained two-date print with Farmer/Reese, a source-explicit June witness, a package-only unresolved witness, and the existing multi-package/same-day collision controls. Retain every source occurrence/locator/context, panels, links and literal affiliations. Under occurrence-v2, changing occasion changes witness_key; account for each key and downstream document-witness-link change in gate-1 cause/disposition evidence. Do not force key stability or invent witness redirects; gate2 separately protects document public link continuity.

Retained held_dates should permit a model-only binding repair, reusing appearance records without parser replay. Prove the exact affected interpretation closure before claiming selective output reuse; final validation/export may still read inherited populations. Fixture work can proceed alongside affiliation, nomination and recording work. No hard dependency on those fixes or new acquisition. Finish source/native values, existing candidate gates and installed selected-release replay; local passing output does not repair unchanged e4538f00.

**2026-11-05T20:18:06Z**

Integrated package-scoped handling for witnesses from multi-date MODS hearing prints. The bounded refresh produced all 35,020 current MODS rows while retaining every prior row. Named multi-day and single-sitting controls passed. Final candidate checks must confirm package context is not promoted to an individual appearance date. Full build/publication waits all waves.

**2026-11-05T23:55:27Z**

The reviewed model keeps ambiguous multi-date print witnesses at package scope, and the qualified MODS replay is imported. Supported single-sitting and print-link controls passed. [Independent Wave 1 acceptance](../.cache/archive-release/implementation/production-mvp-20261105T190929Z/acceptance/SUMMARY.md)

Close implementation. ct-gi01 retains Farmer/Reese occurrence-key causes and document-link continuity; ct-m104 retains selected-reader verification. Check the July link separately: retained event 100099 identifies jacket 72257, and the inspected 72238 inputs do not establish a July candidate edge. Do not invent that edge to satisfy a check.
