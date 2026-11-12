---
id: cat2-ddas
status: closed
deps: []
links: [ct-lft6, ct-17op]
created: 2026-11-12T12:20:24Z
type: bug
priority: 1
assignee: mikewolfd
tags: [parsers, house-naming, xml, horizontal-audit]
---
# Horizontal audit parsers: <amendment-doc> RCP XML titles, >5-digit draft bill numbers, and Rules markup slot <legis-num>

From the 22-slice horizontal raw-data audit (F4 XML, P1-7d, P2-10c): (1) <amendment-doc> HOLC XML renditions of House Rules Committee Prints (e.g. BILLS-116HR2203-RCP116-27.xml, G:\CMTE\RU\16\RCP\RCP_H2203.XML) extract title=null and heading=null in page_facts, leaving 176 BILLS-*-RCP* prints untitled; (2) untyped draft filenames with trailing dates (bills-117pih-1hres___6162021.pdf) mint impossible >5-digit measure_keys (117-hres-6162021, 118-hr-57365430, 117-hres-81022, 116-hr-75757) in house-naming/extraction.py; (3) house_documents.py copies integer Rules markup agenda slot <legis-num>7</legis-num> (event 118455, sha f954b7fc...) straight into committee_records.bill='7'.

## Acceptance Criteria

(1) <amendment-doc> XML extracts print heading / official title in page_facts; (2) house-naming rejects >5-digit bill numbers on untyped date-suffixed drafts; (3) house_documents.py requires a valid measure prefix before setting committee_records.bill; unit tests cover real byte fixtures.

## Notes

**2026-11-12 (`claude/ct-wave-3-parsers`):**
- `(1)` Added `<amendment-doc>` fallback in `packages/congress_api/src/congress_api/parsers/archive_readings.py` (`read_page`) extracting visible `<amendment-form>/<legis-num>` as `heading` and visible `<action-desc>` as `title` without bumping `READING_VERSIONS['xml']` (only `page_facts` for HOLC `<amendment-doc>` files changes).
- `(2)` Added `_MAX_BILL_NUMBER_DIGITS = 5` guard in `packages/house-naming/src/house_naming/extraction.py` and mirrored `_MAX_MEASURE_NUMBER_DIGITS = 5` in `packages/congress_api/src/congress_api/lake/filenames/__init__.py` so untyped date-suffixed drafts (`bills-117pih-1hres___6162021.pdf`, `57365430`, `81022`, `75757`) no longer mint impossible `measure_keys`.
- `(3)` Added `_MEASURE_BILL_PREFIX_RE` guard in `packages/congress_api/src/congress_api/parsers/house_documents.py` requiring a valid legislative measure prefix before populating `amendments[...]['bill']`, keeping bare Rules markup agenda slot numbers (`<legis-num>7</legis-num>` in `f954b7fc...`) out of `committee_records.bill` (intentionally bumping `committee_records.house_xml`).
- Covered with real-byte regression tests across `test_engine_first_readings.py`, `test_ct_29n4_regressions.py`, `test_filename_readings.py`, and `test_committee_records_lake.py`, plus verified end-to-end in `wave3_horizontal_slice_review.md` (Slice 12).


