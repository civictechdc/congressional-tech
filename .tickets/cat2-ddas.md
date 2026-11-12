---
id: cat2-ddas
status: open
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

