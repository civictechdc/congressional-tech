---
id: ct-tk10
status: open
deps: []
links: [cef-96wc, ct-n2cy, ct-qg8e, ct-d0o0, ct-4jms, ct-ud0b, ct-9lxf, ct-umtm]
created: 2026-11-02T10:24:38Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, gates, phase2]
---
# Gate every publish on key comparison, link rule, end-to-end test, write-time schema and producer proof

Owner decision 2026-11-02: all five gates before the next publish. publish_v21 reached live with defects because nothing compared it with the previous release or with raw data, required fields were not refused at write, links vanished silently, and inputs carried a digest but no producer. Each gate must be able to fail on the defect class it covers; a check that agrees with itself is not a gate.

## Acceptance Criteria

- Key comparison: release_diff against the live release by key, value by value, refuses unless every difference group has a recorded cause.
- Link rule: every link key published by the live release resolves in the candidate, by redirect to its successor or a removal notice; none vanish. Covers the 7,266 lost links.
- End-to-end: one fixture runs raw receipts through captures, readings and model to release files, including a ZIP with members, an HTTP 202, an empty 2xx and a NULL URL.
- Write-time schema: required fields (sources.url and others named in the schema) are refused when written, not found later.
- Producer proof: every pinned input records the producing code revision and job; publish refuses an input without it.
- Each gate has a test proving it fails on an injected defect, and the publish workflow runs all five before the pointer flips.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Plan (plan-h): gate 1 release_comparison in publish_candidate (release_diff never failed on value changes); gate 2 retired_links.parquet seeded from c94bfedc/a06e2a63/0db23484 with site and MCP redirect or notice; gate 3 end-to-end in archive_publish_job.execute; gate 4 required fields for all tables (registry declared one of 21); gate 5 per-row producer version (parser_version/catalog_version current or registered-compatible; captures.mapping_version), since writer_job/writer_commit are receipt provenance (NULL on 4,144,875 of 4,147,132 v21 rows). Implementing: impl-h, branch r1b-h.

**2026-11-02T12:36:53Z**

Round 1b 2026-11-02 (lead): impl-h done: 13 commits on r1b-h (1055fefb..36ac49a0), rebased on integrate-round1 76c521a0. All five gates in the real publish path, each with a test that fails it on an injected defect. Offline against 448651e7 (base c94bfedc): gate 1 refuses (69 reasons, 39 value changes); gate 2: 7,266 base keys vanish, all covered by the seeded ledger (7,134 redirect, 132 removal notice; the 132 not yet read raw); gate 4 refuses 72 NULL sources.url; gate 5 refuses v21 captures (no mapping_version); gate 3 is a code test. Waiting on e1's mapping_version (2 strict xfails) and a cause record for the real candidate. Report: .cache/rounds/r1b/h/offline-gates/report.json. Open: the end-to-end test shows a ZIP dip.xml member not listed as a document; check against the data model.

**2026-11-02T13:13:02Z**

2026-11-02 green-h (request changes): numbers reproduce exactly against 448651e7. Defects: (1) removal notices are wrong for 70 of the 132 keys: duplicates at an address whose other document survives, with a successor in 69; the redirect rule never looks at addresses; the 71st (a 403 page) takes a notice. The 61 ZIP-member keys come from the D1 archive-member defect. (2) Gate 1 passes a changed file whose handler finds nothing (e.g. witness values). (3) The link rule never checks that every history key landed in the ledger; impl-h's offline harness redirected 6,260 to the wrong document (the real model is unaffected). (4) dip.xml is never asserted. (5) 114 of 229 columns are declared non-null; review the rest. (6) Gate 5 checks a version per row, not the commit and job. (7) Three publish journeys are xfail on any ValueError. (8) Resume after a successful flip errors (archive_controller.py:296, traced). Waiting for red-h before sending fixes.

**2026-11-02T13:13:51Z**

2026-11-02 red-h (merge with fixes; 179 passed): gate 1 passes, with no cause record, a witness organization rewrite, a source moved between documents, and a url key repointed; link_history is unchecked; strict xfails hide every path to published; evidence on explained entries is optional; the gates pass with nothing checked when the pointer is missing or in legacy format. Every path (CLI, CI, daily) goes through execute, and gate_and_flip is the only pointer writer. Combined red+green fix list (11 items) sent to impl-h.

**2026-11-02T13:59:45Z**

2026-11-02 impl-h: all 11 review fixes on r1b-h (head 5810b591, 19 commits on 98fb1424); full production-offline lane green with no xfails left (3.6 GiB). Gate 1 now refuses red-h's three probes and silent handlers; explained causes need evidence pins. Gate 2 adds address successors (§8.2) and the history chain from the pointer's previous release. The 7,266 lost links become 7,203 redirects and 63 notices (61 ZIP-member keys to recheck on the rebuilt candidate; 1 HTTP-500 ZIP; 1 unlisted sciencedirect article). Gate 3: dip.xml is not a document (§7.3), all six suites run. Missing or legacy pointer refuses unless first_release is declared. Resume after a flip returns release_unchanged. Gate 5 also checks a per-snapshot producer record. Gate 4 finds 17 NULL nominations.description in 448651e7 (upstream check in progress). red-h2 is re-reviewing. Next: ct-ud0b.

**2026-11-02T14:25:28Z**

2026-11-02 red-h2 (merge with fixes): red-h's probes now refuse, and 12 of 17 mutants were caught. The address-successor rule redirects across editions: all 69 address redirects come from version_keys addresses and land on different bodies (7 editions collapse onto 3 documents), against data model §7.5. New rule: redirect only to a successor holding the same body or text fingerprint; otherwise show a notice listing the address's current versions; all 69 bodies to be read. Gate 5's producer record is self-attested (it accepted README.md, the first commit, version 99): recompute the byte-hashed version at the recorded commit and require the table's registered producer. Tests for M1 (first_release with a live pointer) and M10 (link history). Sent to impl-h.

**2026-11-02T14:50:56Z**

2026-11-02 (lead): owner decision: delay the performance gate till later. Site speed targets don't gate this release; the deferral is recorded explicitly in archive-targets.json (status deferred, date, reason, restoring ticket) and in the release record, never as a silent bypass (r1b-targets-defer).

**2026-11-02T15:55:47Z**

2026-11-02 impl-h r1b-h 1573be5c: all review items done; production-offline, explorer-mcp and archive-unit green on 5a3121c. Address redirects: all 69 old and successor bodies read; none is the same text (66 old bodies have none), so all show notices listing the editions at the address. Against 448651e7: 7,134 redirects, 132 notices. Gate 5 recomputes the version at the recorded commit and requires the registered producer and record version 1 (red-h2's probes refuse). M1, M10, M3, M4 and M16 killed. Gate 4: nominations.description nullable; the 17 NULLs (119-PN27 … 1175) are military promotion lists with no upstream description (1,349 of 1,363 empty upstream descriptions are military). Ready to merge after e1, e2, g and f.

**2026-11-02T16:40:28Z**

2026-11-02 (lead): r1b-h merged into integrate-round1 by fast-forward at 0f4711bb (27 commits, rebased onto f5f647da): retired_links, nullable flags merged with g's meanings, lifetimes 177, and fixtures adapted to e1's mapping_version and its build-time refusal of the 202 mutant.

**2026-11-02T17:17:02Z**

Owner decision 2026-11-02: any gate-1 difference group the cause catalog can't match is brought to the owner with evidence and a recommendation before publish. Catalog: .cache/archive-release/causes/ (19 causes, matcher match.py; probe matched 10/11, the 11th being live's 72 NULL source URLs). Gate fix requested (r1b-h2): compare struct subfields individually (meetings.sittings gained fields, 17,441/18,687 rows differ wholesale) and state the 'cannot see' for columns new in the candidate.

**2026-11-02T17:20:05Z**

2026-11-02 (lead): r1b-h2 44785aee merged (ff): gate 1 compares shared struct subfields individually (sittings[].start changes surface), new subfields are their own addition groups, removed ones refuse, and columns new in the candidate are listed under cannot_see.

**2026-11-02T18:19:25Z**

2026-11-02 impl-h (r1b-h3 5ac60b63, on release-train): the video_records staging refusal was the producer's fault, not the validator's. The shared record producer wrote two identity keys and a free-text reason in its unreadable-body decision; data model §5.3 and validate_provenance require one identity and a snake_case reason. It began in 20206037 and moved into _record_producer.py in 3f6548e6. Fix: one unreadable_decision() (record_sha only; the reason is the exception class in snake_case). Every record producer now has an unreadable-body fixture; none had one before. The meeting, appearance, video and committee pins move. Open: the house_xml parsers stamp unreadable bytes as 'completed'; being measured before D4.

**2026-11-02T18:44:42Z**

2026-11-02 causes: .cache/archive-release/causes/run_gates.py runs all five gates on a candidate directory plus the cause matcher and prints a single summary with unmatched groups; RUNBOOK.md drafts the publish steps (upload, pointer flip, live checks, rollback, main merge with the runtime pin and the DOCSPEC_RUNTIME_ARTIFACT variable). Dry run on the probe failed cleanly, peak 0.93 GiB: gates 1 and 2 (the probe has no retired_links; 2 unmatched groups), gate 3 (the fingerprint column drift, being fixed by impl-e2), gate 4 (72 NULL source URLs), gate 5 (v21 has no producer records). Also found: .github/archive-jobs.json has no rss_gb (every hosted job refuses; set at the main merge), and release_gate compare has no --history.

**2026-11-02T21:48:41Z**

2026-11-02 owner decision: recovered documents that are byte-identical (sha and size) to an already-published document merge into it by body hash: their dead-link addresses and recovery records attach to the copy instead of standing as their own documents. That is 4,060 exact copies, including the 44 blank-filename rows that failed the release invariant (41 democrats-edworkforce download?id=GUID links, 1 democrats-transportation, 2 waysandmeans ?p=N; copies are 42 docs.house.gov witness PDFs and 2 W&M uploads). 172 recoveries of other kinds stay separate. Owner: 'this is all greenfield so redirects aren't really needed yet', so no new redirect machinery; link keys resolve through the attachment, and the existing retired_links path records vanished document ids if gate 2 needs it. Model only (about 9 min). inv-rca implementing on r1b-inv; causes catalog updated.

**2026-11-02T21:49:48Z**

2026-11-02 owner on the merge by hash: 'Don't lose signal. Maybe that was added from a committee page and the other was from somewhere else. How do we merge the metadata in?' Rule given to inv-rca: (1) each merged address keeps its own provenance (source page, link text, meeting, first and last seen, URL state, recovery record); (2) document fields are combined: the copy's value is shown, the recovered row fills nulls with its source address noted, and conflicting non-null values are kept as alternates with their source; (3) a no-signal-lost audit refuses the run if any non-null field or links, urls or recoveries row of a removed entry doesn't reappear on the merged document. Conflict counts and examples go to the owner before publish.

**2026-11-02T22:27:53Z**

2026-11-02 inv-rca 35c6e077 (merge by fingerprint, keeping every signal): 4,106 links merged into 3,747 documents; list goes from 359,690 to 355,608; all six invariant suites 0; blank reasons 79 (query 75, host 4); an independent DuckDB audit of old vs new found 0 addresses, recovery rows or values lost. New refusing invariant unaccounted_merged_signal plus metadata merged_recovery_fields. Fills from the link: title 1, congress 51, date 20, package 28, kind 51, family 51, facts 38. Conflicts (copy shown, link kept on its source annotation): filename 3,379, kind 1,104, facts 1,460, family 235, package 32, date 13, congress 12, title 0. Some conflicts suggest wrong accepted recoveries (a Wstate link recovered with the same witness's Bio PDF; a 103rd-Congress link recovered with a 114th-Congress body); being counted for the owner.

**2026-11-02T23:03:28Z**

2026-11-02 the 36 strong conflicts (congress 12, cross-class kind 18, person 1, date over 7 days 5; all live in 448651e7 with the same body) are not wrong recoveries. In the five read against content, the docs.house.gov copy's filename mislabels it (statements filed as Bio-…, an opening statement as Transcript-…), so the copy-first display shows House's wrong label. Owner: 'Shouldn't we have a triage list or some way to correct/override mistakes? The conflict is useful. But ultimately we want correct data.' Plan, reusing the existing review provenance path (review_provenance.py; hide, title_override and kind_override verdicts): the model emits a ranked conflict triage list as internal evidence; inv-rca reads all 36 against content and drafts review records with evidence for owner approval; any extension for congress, date or person is minimal; both source values stay.
