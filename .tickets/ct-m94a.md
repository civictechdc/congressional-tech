---
id: ct-m94a
status: open
deps: []
links: [ct-wx65, ct-gi01, ct-m104]
created: 2026-10-31T00:05:23Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, dates, coverage, chaos-test]
---
# Qualify filename-derived document dates and publication coverage

The retained release advertises document coverage through 2303-05-04 with gaps=[]. A bounded audit found 11 document dates after 2100. For FDA PAHPA testimony May 4 2303 HELP1.pdf (list_row 161961), the parser correctly preserves the literal year and marks its role unknown, but the producer promotes the single candidate into filename_date and publication treats it as a coverage bound.

This is a qualification-policy gap distinct from the bill-number/date overlap bug. Current model documentation explicitly promotes a single date candidate and prefers filename dates, so correcting the behavior requires an explicit model-policy change. The historical date of this document has not been adjudicated; changing 2303 to 2023 would be a guess.

Diagnosis: source revision 052b6111cb816b81446cf29b7b2d82aad5517d05; retained release 0db23484fe86c7f5a5e50e44f078ec34e74e793873b26c4a15f0b9e9efa17b69. Local evidence: .cache/chaos-mcp-20261030T233124Z/diagnosis/report.md and its probe files. That ignored local directory may not exist in another checkout; the decisive reproduction is included below. Tests establish local source behavior, not current public-pointer or installed-package behavior.

## Design

Owners: congress_api/lake/filenames/_typed, model/sql/source-annotations-filename.sql, source-annotations-final.sql and document-normalized.sql; viewer_publication/archive_format.py; shared schema/documentation and site/MCP consumers.

Define an explicit, reproducible policy for accepted, unresolved and suspect document dates, using existing provenance and uncertainty fields where possible. Preserve literal filename evidence and useful candidates. Calendar validity alone does not establish a date's role. Document how supported source context, conflicting assertions, missing values and short-year precision affect selection and classification. Never silently clamp years, repair digits or infer centuries.

Publish the accepted date span with dated/undated/suspect counts and enough qualification detail to account for unresolved candidates without double counting. Define the counting units and categories. Expose date source and uncertainty; label an observed span as such, because its endpoints cannot establish completeness or the absence of gaps. Keep completeness claims separate and evidence-based.

Calculate these summaries in the existing publication aggregation and keep site/MCP consumers faithful to the shared release; do not add repeated MCP scans or a separate date calculator. Prove the policy on fixed small inputs before regeneration. Coordinate with ct-wx65 and ct-m104, assess actual parser-version invalidation, and reuse retained inputs. Do not assume that only affected filenames can be recomputed; combine required date-generation work where practical.

## Acceptance Criteria

- Document and implement the date-selection and classification policy, including candidate role, conflicting evidence, missing values, short-year precision and any precedence change. Update the existing model/schema reference coherently.
- Preserve the literal May 4 2303 observation. It must not become an unqualified historical coverage claim or be silently rewritten to a guessed date. State its classification and the evidence or rule supporting it.
- Test a qualified content/event date, an unknown-role filename candidate, a suspect candidate, conflicting dates, an undated document and a short year. Published accepted bounds and dated/undated/suspect counts, with unresolved-candidate accounting, must agree with independent expectations on fixed inputs.
- A date span or empty gaps list must not imply complete historical coverage without supporting completeness evidence. Document the meaning of bounds, counts and gap metadata, including unavailable or unknown evidence.
- Compute qualification summaries in the existing publication path. Verify date source, uncertainty and summary discovery through actual stdio MCP against the compact native fixture and through the site where exposed; label local candidate versus selected/deployed release evidence separately.
- Keep parser-overlap errors distinct from literal but unqualified observations. After fixture verification, record required regeneration scope and resource budget under the actual version rules; reuse retained inputs, preserve raw evidence and record exact input/definition/release pins.

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
