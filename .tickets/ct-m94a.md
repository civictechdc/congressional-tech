---
id: ct-m94a
status: in_progress
deps: []
links: [ct-wx65, ct-gi01, ct-m104, ct-9xfg, ct-nozw]
created: 2026-10-31T00:05:23Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, dates, coverage, chaos-test]
---

# Keep unsupported download-alias dates out of archive coverage

Researchers should see the observed dates the archive can support and why individual dates are uncertain. Baseline release `e145d24c389e` reports observed dates from 1901-02-27 through 2026-10-23. Three accepted 1901 dates point to 2019 proceedings.

## Root cause (2026-11-05)

The selected readings leave the displayed filename tokens `02 27 19`, `03 26 19` and `06 19 19` unresolved. The model fills their dates from linked Senate download names `transcript-02271901`, `transcript-03261901` and `transcript-06191901`, even though each supplied date has `filename_date_valid=false`. Document date ranking accepts those candidates as plausible because they precede capture and have no Congress value. Publication labels them accepted and includes them in the observed bounds. The three confirmed failures are in alias-date selection. The earlier stale displayed-name diagnosis is retired for these cases.

## Merged repair and release checks

Local `main` includes `315145ca` and `b57c02ad` through merge `18049548`. The model excludes the demonstrated opaque Foreign Relations alias dates from selection while retaining the literal names, dates and source URLs. It reuses the pinned filename readings.

The seven-document native fixture read back through MCP over standard I/O and the site. The three unsupported aliases were undated. The genuine `1901-03-02` date without a Congress tag and both supported alternate-name dates survived. The literal `2303-05-04` remained suspect. MCP counted three accepted, one suspect and three undated documents, with accepted bounds of `1901-03-02` to `2021-03-17` for this fixture. [MCP evidence](../.cache/archive-release/implementation/production-mvp-20261105T190929Z/dates-captions-recovery/date-reader-stdio.json) · [Site evidence](../.cache/archive-release/implementation/production-mvp-20261105T190929Z/dates-captions-recovery/date-reader-browser.json).

After the all-wave hold, the release coordinator owns the combined candidate's independent bounds and unresolved-date accounting, followed by selected-release MCP and site readback. [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md).

## Acceptance Criteria

- Check the three aliases against their exact selected rows. Keep the shown-name tokens and alias values traceable and exclude the unsupported 1901 values from accepted bounds. Include an independently dated genuine 1901 control with no Congress value and a supported alternate-name date. Select the genuine control before qualification. Check source role and precedence, conflicting dates, unknown role, short years, suspect and undated results. The literal May 4, 2303 case remains suspect with its source.
- Account for unresolved candidates once. Independently confirm accepted bounds and accepted, suspect and undated counts. Label the bounds as observed dates, explain where coverage evidence is unavailable and preserve the separate meanings of retrieval and capture times.
- Use the existing native fixture and publication aggregation. Verify date status, source, counts and bounds through actual MCP standard I/O and the site where exposed. Record local candidate and selected live readback separately.
- If another exact filename/URL/parser pair proves stale, record the affected predicate, resource budget, input and code pins and authoritative table handoff before replaying that subset. Reuse applicable readings and leave the confirmed alias fix at the model boundary.
- Use the published `document_date_status` for recent-document lookup in MCP. Default chronological results to accepted dates and offer an explicit way to include suspect or undated rows. Preserve their literal dates, source, and qualification in the result. On a release without date status, describe that limitation and preserve access to literal dates.
- Exercise the default and explicit inclusion paths through MCP. The literal `2303-05-04` control stays visible on explicit inclusion and cannot lead the default newest results. Preserve exact document lookup, the genuine 1901 control, and arbitrary read-only SQL.

## Coordination and evidence

The model owns date eligibility. Publication owns status and bounds. [ct-cxc5](ct-cxc5.md) owns printed-cover date disagreements and can share a release readback. [ct-wx65](ct-wx65.md) applies if another stale reading is established. [ct-m104](ct-m104.md) owns release reader acceptance. [Root-cause evidence](../docs/plans/production-mvp-root-causes-20261105.md).

## Notes

**2026-11-04T02:25:25Z**

Chaos-test addendum (2026-11-03, served release e4538f00…, run chaos-congress-mcp-20261103): the 1901-02-27 start bound and congress_start=12 are the same filename-driven family as the 2303 end bound. (1) 9 documents dated before 1915, all document_date_source=filename: '02 27 19 Assessing The Role Of The United States In The World2.pdf' (list_row 765), '03 26 19 US Policy Toward North Korea After the Second Summit1.pdf' (1536), '06 19 19 Nomination of Kelly Craft … United Nations.pdf' (4884) — externally verifiable 2019 events, two-digit-year misreads. Current-code check (review 2026-11-03): today's extractor returns no date for these; the 1901 values come from older stored filename_readings, so this slice needs regeneration rather than a parser change. (2) congress_start 12 comes from two documents whose filenames literally read HHRG-12-… and hhrg-14-… — publisher typos of 112 and 114, read faithfully by the parser, the same class as the May 4 2303 typo and not a parser bug: HHRG-12-AP07-WState-JCarbone-20120321.pdf (list_row 271949, 2012 file → 112th) and hhrg-14-sy16-wstate-jgabrynowicz-20160907.pdf (31910, 2016 file → 114th); published coverage advertises '12th–119th Congress'. (3) In release e4538f00 the FDA PAHPA file is list_row 154894 (ticket cites 161961 from retained release 0db23484…); its source URL preserves the publisher's literal typo (help.senate.gov/imo/media/doc/FDA%20PAHPA%20testimony%20May%204%202303%20HELP1.pdf), supporting the literal-preservation stance. (4) Boundary counts in e4538f00: 22 documents dated after 2026-12-31, 9 before 1915, 2 with congress<57, all filename-sourced; out-of-context dates (term-expiry 2031-01-19 / 2027-11-12, 'year to 31 March 2027') are a distinct cause from publisher typos and short years.

**2026-11-04T03:28:13Z**

Policy decided and implemented locally (uncommitted, 2026-11-03). Decision: flag, don't rewrite. detail.document_date_status = 'accepted' | 'suspect' (null when undated), computed once in the publication `ordered` step (archive_format.DOCUMENT_DATE_STATUS). A date is suspect only when document_date_source='filename' AND (document_date > first_captured + 30 days OR year outside the tagged Congress's years [1789+2(n-1)-1, 1789+2(n-1)+3]). Content and meeting dates are always accepted. document_date keeps the literal reading (2303-05-04 stays, labelled suspect). The 30-day allowance exists because committees post hearing documents before the hearing date: HHRG-119-ED00-20261023-SD001.pdf was captured 2026-10-15 for a 2026-10-23 hearing and would otherwise be a permanent false alarm.

Coverage: list/detail (and links/urls/sources/recoveries) date bounds use accepted dates only; Congress bounds skip suspect-dated rows; witness date fallbacks use accepted dates. list/detail coverage adds document_dates={accepted,suspect,undated}. list/detail gaps state that bounds are observed values, not completeness evidence. Schema, reference doc, MCP (search/entity document summaries include document_date_status when the release publishes it; the search_documents description says how to read it) and site (detail page labels a suspect date "read from the filename; likely misread") are updated.

Measured on served release e4538f00 with the same rule (DuckDB over the cached detail.parquet): 263,085 accepted, 47 suspect (22 too far after capture, 25 contradicting their Congress), 92,476 undated. Coverage would become Congress 104–119 and dates 1901-02-27 → 2026-10-23. The 1901 start remains because the three short-year files ('02 27 19 …', '03 26 19 …', '06 19 19 …') have no Congress tag and an old capture; today's extractor returns no date for them (test pinned in test_filename_readings), so regeneration of those filename_readings fixes the start bound.

Tests: test_archive_release::test_suspect_filename_dates_keep_their_reading_and_leave_coverage (fixed inputs; each of the capture rule, the Congress rule, the filename-only scope and the 30-day allowance was planted wrong and the test failed). MCP reader tests cover old releases (field absent) and new (field carried). Site unit and reader-contract tests updated.

Not done: unresolved-candidate accounting beyond the three counts; stdio MCP verification against the compact native fixture (needs --native-fixture-root from the producer runner); regeneration scope and budget. Local viewer_publication lane has pre-existing failures from the sniff parser pin drift (publish-model.json sniff 01bf0900… vs current 22b4118e…), unrelated to this change.

**2026-11-04T15:07:16Z**

2026-11-04 accountability investigation: keep local date qualification distinct from live date coverage. Live release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; checkout inspected separately at 730a2d8e0c55880fc058d13cc74d265fc315f41f. This is ticket-only follow-up to chaos-personas-20261104; no repair, tests, source regeneration or publication was performed. Fresh runtime schema is retained in .cache/archive-release/chaos-personas-20261104/ticket-accountability/runtime-check.json.

Fresh live discovery still reports unqualified document coverage congress_start=12, congress_end=119 and dates 1901-02-27 through 2303-05-04 with gaps=[]; detail lacks document_date_status. The complete discovery response is retained at .cache/archive-release/chaos-personas-20261104/ticket-accountability/runtime-check.json. This confirms the selected release has not adopted the already-described local classification; it is not evidence that the local policy was lost.

At the inspected checkout, viewer_publication/archive_format.py:54-59 defines DOCUMENT_DATE_STATUS, :127 computes it once in ordered, and model/registries/release-schema.json:117/366 says accepted bounds are observed values rather than completeness evidence. No code or test was changed/run here; keep this ticket open for its remaining acceptance and delivery, rather than implementing a second date calculator or closing from source inspection.

Separate research limitation from this defect: sources.posted has zero populated values among 577,181 source occurrences on e4538f00 (investigation-accountability/calls.jsonl call 2). first_captured and source first_seen are retrieval/observation fields, so document_date-to-first_captured is archive capture delay, not committee publication lag. This note does not prove raw publisher add dates were dropped and does not expand this ticket into an unsupported ingestion bug.

Smallest next acceptance: complete the existing fixed-input/uncertainty accounting and real consumer verification, record regeneration scope and exact pins, then qualify/publish and read back selected bounds, counts and document_date_status. Keep literal publisher observations; do not silently rewrite 2303 or claim gaps=[] proves complete history.

**2026-11-04T15:23:03Z**

Coordinated producer plan frozen 2026-11-04: docs/plans/congress-explorer-root-cause-remediation-20261104.md. This addendum refines remaining work without rewriting prior evidence. Live evidence remains release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; source inspected at 730a2d8e0c55880fc058d13cc74d265fc315f41f. Planning/ticket update only: no implementation, tests, prepare, acquisition, data changes or publication.

Owner remains shared publication date policy and required stale filename-reading correction, not another reader date calculator. Current local archive_format.py:54-59/127 and registry 117/366 already classify dates/qualified observed bounds; selected e4538f00 has not adopted them. Preserve literal document_date and provenance, accepted/suspect/undated meanings and unresolved accounting; never rename first_captured/source first_seen into publication time or treat an empty gaps list as completeness.

Complete the existing compact source/native fixture and consumer acceptance, as additions to maintained tests; no new global raw-audit runner. Qualification-only model changes reuse readings. Re-extract filename readings only for proved stale/misparsed inputs (coordinate ct-wx65) under the actual affected pin predicate; do not reparse all bodies to qualify bounds. A changed parser still needs one selected version/key, reviewed field/key dispositions, published spec pin and authoritative catalog continuity.

Date fixtures and metadata qualification can proceed alongside other producer/recipe work. Any filename semantic replay depends on its exact input predicate and existing parser-owner decision; the publication-only rule does not depend on historic roster acquisition or witness repairs. Retain exact input/definition/candidate identities and reuse valid completions. Existing gates and actual stdio/site readback must show the new counts/status/bounds before closure; local implementation and this plan are not live completion. Full replay cost is not measured or assumed.

**2026-11-05T20:18:06Z**

Integrated the qualification fix for opaque Foreign Relations download aliases; no replay of unchanged filename parsing is needed. Retained browser and MCP checks leave the three unsupported aliases undated, preserve supported alternate names and a genuine historical 1901 date, and flag the 2303 control. Final combined-candidate and live checks remain due. Full build/publication waits all waves.

**2026-11-05T23:55:26Z**

Implementation review: the original unsupported-alias qualification fix is merged and independently accepted, including the genuine 1901, alternate-name and suspect-date controls. Keep this ticket open for the newly added MCP chronological default, explicit suspect/undated inclusion and older-release behavior. Those lookup changes are not established by the original model/date checks. Preserve the concurrent additions; final reader acceptance remains with ct-m104.

**2026-11-06T16:53:24Z**

2026-11-06 scoped acceptance: verified exact archive SHA-256 and original covers for the three 2019 aliases, two supported alternate names, the 2303 literal and an additional Turkey-hearing descriptive alias. Retained native 720c495b still accepted 1902-10-22 from that Turkey alias; its cover independently states October 22, 2019. Isolated commit a244e5f3 on codex/ct-m94a-residual-alias-20261106 excludes only that demonstrated invalid alias in the existing model qualification. The new native regression failed before the fix; all 5 tests in test_filename_both_names.py passed afterward (production-offline partial, 0.50 GiB peak). No parser change or reading replay. Genuine March 2, 1901 GovInfo original was selected and independently read before qualification; an 8-original native control with a controlled displayed historical filename retained it with Congress null, accepted both supported names, kept 2303 literal/suspect and left 4 unsupported aliases undated. 43 normal stdio calls and 5 wrong-value/missing/extra-row plants passed in that bounded control. Authentic baseline has no genuine pre-1915 row, so this historical control is explicitly separate from the shared release. Evidence and prepared actual-release audit/stdio checks: .cache/archive-release/mcp-research-20261106/parallel-sessions/ct-m94a/. Shared native candidate, actual counts/bounds, site and selected-live readback remain pending ct-m104. Keep ticket in_progress; coordinator must review and integrate a244e5f3 before final source freeze.

**2026-11-06T18:43:09Z**

2026-11-06 owner update: Independent ct-m94a work is complete. Commit a244e5f395db37c3b279e62ccb6da5d8d397ea9f excludes the remaining unsupported Turkey download-alias date while preserving its literal reading and source; it is independently approved and present in integration 924e3ef238130a435a89449d1b5ddb7d7cf1b955. Five focused native tests passed in a partial production-offline lane, and 43 normal MCP stdio calls passed in bounded controls; these do not establish a full production lane or final-release acceptance. Those controls preserve supported alternate-name and genuine 1901/no-Congress dates, keep unsupported aliases undated, and retain literal 2303 as suspect with explicit access while excluding it from default recent lookup. Eight original PDF hashes/covers and five fault plants were independently confirmed. The historical body is authentic, but its displayed filename is controlled and it is not a published historical row. Evidence: .cache/archive-release/mcp-research-20261106/parallel-sessions/ct-m94a.md and parallel-sessions/ct-m104/m94a-source-review.json. This is local qualification, not live delivery.

Remaining: daily planning qualification is complete/source-freeze-ready at d2ec0211 and the related accepted daily commits; it is no longer a blocker owned by ct-082q/ct-irxg. Root owns the consolidated source rollup. The shared House-transition/model-repair gates and final source qualification must clear before ct-m104 produces the sole final native candidate, confirms actual date counts/bounds, and completes candidate plus selected-live MCP/site checks. Keep in_progress until those release checks pass. Independent work is complete; closure is not ready.

Current review follow-up: a direct-URL alias eligibility recurrence is under focused investigation. The original blind review continues unchanged. No affected production row is claimed; closure remains not ready.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at 764235b3. Shown and linked URL readings now share one eligibility rule, so direct alias URLs cannot reintroduce unsupported dates. Literal readings, supplier provenance and each disagreement are preserved. Eight alias cases and one reference-association case passed; the retained eight-original control rebuilt to identical public bytes.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Actual final native date counts/bounds and candidate plus selected-live MCP/site checks after the shared input transition. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-m94a/REVIEW.md).
