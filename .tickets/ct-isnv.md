---
id: ct-isnv
status: in_progress
deps: []
links: []
created: 2026-11-10T14:57:27Z
type: bug
priority: 1
assignee: mikewolfd
tags: [site, mcp, model, release]
---
# Exact-kind filters lose about 7,550 testimony documents when official names lead

Found by the model review of the next-release stack (.cache/archive-release/investigations/next-release-review-20261110/model/REVIEW.md, Q1 and finding 4) on the first full build (release-next/build-c03c43da). The name rule (ct-h8dr) moves 16,342 documents to the official House kind vocabulary: testimony -> witness-statement 7,658, opening-statement -> member-statement 623, and so on. The moves are right (documents with no kind fall from 45,340 to 39,997), but two exact-kind filters then silently show about 7,550 fewer 'testimony' documents: the site's Document type menu and bookmarks, and the explorer MCP's search_documents. The MCP's hearing reader already treats the two kinds as one.

## Acceptance Criteria

One owner for kind synonyms (a map, not three lists); the site's Document type filter and saved bookmarks, and MCP search_documents, return the same documents for 'testimony' before and after the name rule, measured on the all-in build; a release note line says the kind words changed.


## Notes

**2026-11-10T19:23:54Z**

2026-11-10 WIDENED: the release's cause record measures the same loss for other exact-kind filters, not only the testimony pair this ticket fixed: amendment 4,975 -> 3,687, opening-statement 5,324 -> 4,682, statement 4,355 -> 3,980, legislative-text 1,060 -> 751, biography 1,288 -> 1,042, committee-report 374 -> 216, transcript 1,214 -> 1,116 (documents now take the kind their official file name states, so a document listed under one word and named under another is counted once). Family filters barely move. Open work: decide per pair whether the Explorer and site should treat the words as synonyms, as was done for testimony / witness-statement; recorded as an accepted defect in the release's cause record.

**2026-11-10T20:38:46Z**

2026-11-10 what release 77673bfb8fcf shows. Checked on published release 77673bfb8fcf (2026-11-10T20:27:52Z) against 619db5f9e08e with DuckDB on the published tables. schema.json publishes one synonym group, document_kind [witness-statement, testimony]. Documents carrying either word: 63,354 -> 64,128 (no loss); the bare word 'testimony' alone 32,200 -> 24,762. The other words still lose under an exact filter, as widened above: amendment 4,975 -> 3,687, opening-statement 5,324 -> 4,693, transcript 1,214 -> 1,134, committee-report 374 -> 216. Not checked here: that the site's Pages deploy and an Explorer release reading the synonyms are live.

**2026-11-11T14:42:31Z**

validated 2026-11-11, left open for the widened decision only. The testimony part is done and live: schema.json of 77673bfb8fcf publishes one synonym group document_kind [witness-statement, testimony]; the site reads it (apps/site/src/components/explorer/reader/kind-synonyms.ts, deployed by Pages run 42917865017 at 515ecb0e), Explorer reads it (congressional_explorer_mcp/release.py:34-41), Explorer 0.6.6 is on PyPI and the hosted Explorer was redeployed on 77673bfb8fcf with 0.6.6 (decisions-overnight 22:48Z, 01:05Z); docs/releases/2026-11-10-77673bfb8fcf.md lines 36-39 say the kind words changed. Remains: the owner's per-pair decision whether amendment, opening-statement, statement, legislative-text, biography, committee-report and transcript get synonyms too (losses listed in the 'WIDENED' note).

**2026-11-11T16:08:58Z**

2026-11-11 BUILT on branch claude/ct-govinfo-synonyms (a24bd689 tests, bcc66135 registry; local, not pushed). Owner's choice: add the clear pairs as synonyms. One owner stays model/registries/release-schema.json (list.parquet synonyms, House guide word first); the site (kind-synonyms.ts) and Explorer (release.kind_words) read the published groups with no code change. Evidence: documents paired 619db5f9e08e -> 77673bfb8fcf by link key (322,644 paired, 16,514 changed kind); investigation govinfo-synonyms-20261111 gs-30..35.

Pair (House word = committee word) | moved | committee word before -> after | either word before -> after | verdict
- committee-amendment = amendment | 1,279 of 1,327 (46 to committee-vote) | 4,975 -> 3,687 | 19,616 -> 20,847 | ADDED. Both are amendments offered at a committee or subcommittee markup: moved "AINS-to-H.R.-5861.pdf" -> BILLS-118-HR5861-S001195-Amdt-4.pdf; the 3,687 left sit on committee markup pages (House Judiciary 924, Ways and Means 394, Senate HELP 370, Foreign Relations 358, congress.gov meeting files 235, docs.house.gov 191); outliers read: 37 cprt-113-ba00-ovplan-*-amdt (amendments to Financial Services' oversight plan), 1 Senate Rules managers' amendment.
- witness-biography = biography | 224 of 246 (20 to witness-statement: statement+bio files) | 1,288 -> 1,042 | 22,644 -> 22,527 | ADDED. Biographies of people appearing before a committee: witnesses, hearing panelists (Human Rights Commission bio sheets, 116), nominees and witnesses at Senate Rules (101). The House "Bio" name is used for government witnesses too (HHRG-115-GO00-Bio-DeVriesD, OPM CIO), so the guide's "non-governmental" does not narrow use. The 117 fewer are documents whose official name now says testimony, disclosure or statement.
- member-statement ~ opening-statement | 623 of 642 (19 to witness-statement) | 5,324 -> 4,693 | 10,583 -> 10,938 | JUDGMENT CALL, not added. Mostly Members' opening statements, but the words cut different ways: "opening" is when, "member" is who. 3% of moved opening statements were witnesses'; member-statement also holds statements for the record.
- committee-transcript ~ transcript | 32 of 99 (67 to published-hearing) | 1,214 -> 1,134 | 3,836 -> 3,869 | JUDGMENT CALL, not added. The 1,134 left are mostly committees' own transcripts (Senate EPW 224, Armed Services 177, Ways and Means 102), but committees also label GPO prints "Official Transcript": two thirds of the moved ones were published hearings.
- witness-statement / member-statement vs statement | 329 / 48 | 4,355 -> 3,985 | - | NOT a synonym: "statement" is the broader word (witness, Member and for-the-record statements); family "statement" already groups them.
- bill-numbered vs legislative-text | 236 (+50 bill-untyped-numbered, +28 bill-unnumbered) | 1,060 -> 751 | - | NOT a synonym: broader (reported, suspension, unnumbered drafts); family "legislation".
- committee-amendment-described / published-report vs committee-report | 142 / 16 | 374 -> 216 | - | NOT a synonym: the 142 were amendment files mislabeled report (crpt-115-hr4659-...-amdt-002.pdf), a correction; the 16 are GPO's published edition (CRPT) of a committee's report (HRPT).
- published-hearing vs transcript | 67 | - | - | NOT a synonym: a GPO print is another publication.

Not done here: the release note line ("the kind words changed; amendment and biography now filter with their House words") belongs to the next release's notes; Explorer needs no new release (0.6.6 reads the groups).

**2026-11-11T16:25:45Z**

2026-11-11 tests: schema 32 passed; Explorer lane (full lane) 224 passed, 4 skipped; site npm run test:explorer 115 pass. Site and Explorer code unchanged.

**2026-11-11T16:58:12Z**

2026-11-11 owner answers built (1d749138 tests, af3308cf change): member-statement = opening-statement and committee-transcript = transcript added to the synonyms map (five groups now). Labelling: a committee's 'transcript' whose saved text opens with a GPO printed hearing's cover (page signal gpo_printed_hearing_cover: hearing number + GPO imprint) reads published-hearing in kind and family; 'committee-transcript' documents keep their label. The model reads no PDF text, so PDFs keep their label. Per-label counts on 77673bfb8fcf (DuckDB, not a build): retagged 17 (7 recovered GPO texts, 10 House Veterans' Affairs pages reproducing the print); transcript 1,134 -> 1,117; committee-transcript 2,735 -> 2,735; either transcript word 3,869 -> 3,852; published-hearing 36,867 -> 36,884. Cannot tell apart: 1,113 transcripts whose text the model does not read (pdf 1,072, other 37, doc 3, docx 1), left as they are; 4 HTML transcripts were read and show no cover. Statement words: opening-statement 4,693, member-statement 6,245, either 10,938. Follow-up: parsers/document_cover.py already recognises House and Senate print covers on a PDF's first page; once PDF text reaches the model it can tag the PDFs the same way.

**2026-11-11T17:16:31Z**

2026-11-11 tests on af3308cf (runner, partial lines): model/schema/registries 35, nearest 21 model files 260 (repeat cost unchanged), test_phase2_model_entities.py 53, release e2e/provenance/evidence/page metadata + test_capture_scheduler.py 134, Explorer synonyms 4, site kind-synonyms 3; all passed. No full lane or build.
