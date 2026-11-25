# Congressional data source audit

Which of the legislative-branch data sources that GPO lists could feed each Congressional Tech proposal, and where are the gaps?

- **Source list:** the Data tab of GPO's Innovation Hub, [usgpo.github.io/innovation/data](https://usgpo.github.io/innovation/data) ("Legislative Branch Data Map", published by the Congressional Data Task Force). Machine-readable copy: [data.json](https://usgpo.github.io/innovation/data.json); source file on GitHub: [`_data/data.json`](https://github.com/usgpo/innovation/blob/master/_data/data.json), last changed **2026-09-10** ("Fix CDTF-DATASET-11 URL"). Read on 2026-11-18: **119 sources**.
- **Proposals:** [civictechdc.github.io/congressional-tech/proposals](https://civictechdc.github.io/congressional-tech/proposals/). The page header says 19, and that is the number of open proposals. The page also lists **V.1 Google Sheets Inflation Calculator**, which is already built, so this audit covers **20**.
- **Why:** the [June 2026 priorities](https://congressional-tech-backlog.netlify.app/updated-priorities) from the meeting with Daniel Schuman (American Governance Institute) list "Audit usgpo innovation data sources" as a new action item ("we absolutely must audit their data sources"), so that new projects know what data already exists before building. Daniel curates the official and unofficial sources on that data tab.

Files in this folder:

| File | What it holds |
|---|---|
| `data-source-audit.md` | This report |
| `data-sources.csv` | One row per source (119): run by, coverage, format, key, stated update frequency, proposals it could feed, flag, plus the 2026-11-18 link check and the latest date seen |
| `proposal-coverage.csv` | One row per proposal (20): June 2026 status, coverage verdict, matching sources, what is missing |
| `flags.csv` | Sources flagged as stale, wrong in the catalog, internal-only or limited |
| `SHOWCASE.md` | One slide for the deck for Daniel Schuman |
| `slack-post.md` | Draft post for #congressional-tech or a GitHub issue |

## What we found

1. **A handful of sources do most of the work.** 56 of the 119 sources could feed at least one proposal, and five carry most of it. The [Congress.gov API](https://api.congress.gov) (#55) feeds 11 proposals. The [GovInfo API](https://api.govinfo.gov/docs/) (#29) feeds 9, and [GovInfo bulk data](https://www.govinfo.gov/bulkdata) (#38) feeds 5. The [House Committee Repository](https://docs.house.gov/committee) (#76) feeds 7 and the [Senate Hearings XML](https://www.senate.gov/general/committee_schedules/hearings.xml) (#110) feeds 6. Of the 119, 107 are open with no key; the two big APIs need one free api.data.gov key. Most of the other 63 are home pages, documentation, executive-branch regulations, disclosure sites and the ten Senate nominations feeds; with III.4 (the newsletter) taken on by AGI, no open proposal uses the nominations feeds.
2. **The top June priority isn't covered.** For the Appropriations Notices & Deadlines Tracker (IV.3), the listed sources give hearing dates only. The House and Senate Appropriations Committee and subcommittee pages, and the testimony-instruction PDFs Daniel tracks by hand, are not on the list. Two other proposals have no source at all: II.3, which needs each Member office's request form, and V.1, which needs inflation (CPI) data. II.1 and II.2 are browser tools and need no data. Overall: 8 proposals covered, 7 partly covered, 3 gaps, 2 need no data.
3. **The Senate is the recurring gap.** The House side is well covered: docs.house.gov has every committee meeting with event IDs, witnesses and documents, plus XML floor schedules. The Senate side has upcoming hearings only (#110), with no hearing history, documents or witness lists. It has no floor schedule feed, only an annual calendar that still points to 2025. That leaves four proposals partly covered: I.1 (hearing platform), II.4 (floor schedule to iCal), III.3 (hearing transcripts) and III.5 (witness database). Three more are partial for other reasons: I.2 needs committee YouTube channels, II.5 needs USAJOBS and the House Employment Bulletin, and I.3 needs disbursement reports from before 2009.
4. **No source looks abandoned, but eight links don't work for the public.** The catalog has no per-source "last updated" field; the only date is the file's own last change, 2026-09-10. So we checked every link on 2026-11-18.
   - **The data feeds are current.** 97 links answered. The Senate nominations, hearings and member files, and the House member file, have records from this week. The volunteer congress-legislators data was updated on 2026-11-15.
   - **Two links are broken or moved.** The House Administration committee reports (#75) return 404 and now live at [cha.house.gov/member-services/monthly-reports](https://cha.house.gov/member-services/monthly-reports). Senate Lobbying Disclosure (#111) returns 503 at its listed address and answers at [lda.gov](https://lda.gov).
   - **Six sites aren't reachable from the public internet:** HouseCal (#90), HouseNet (#91), LegiDex (#92), MemRec (#93), Webster (#117) and CRS.gov (#8). HouseCal and LegiDex looked useful for the schedule and deadlines proposals, but outsiders can't use them.
   - **Three are stale or quiet.** The Senate calendar link (#105) holds only 2025 dates, although a 2026 file exists. The Bill Status GitHub guide (#31) was last updated in September 2024, and House XML Resources (#88) in August 2024.
   - **The catalog has errors too.** #97 has the same URL as #102 plus a description of a different, discontinued collection. The USAspending, CBJ and Capitol Visitor Center download links point to other sites, #69 says shapefiles when the files are KML, and the district shapefiles (#2) are for the 118th Congress.
   - **14 sites blocked our automated check (403/406).** They include Congress.gov pages, loc.gov, CBO and the GPO catalog, so they are not tested, not dead. The Congress.gov API itself answered normally.

   Altogether 28 entries are flagged below, and the catalog fixes can go back to GPO.

## Method

1. Downloaded `data.json` (the same 119 entries as the web table) and generated the table skeleton with a small script, so names, links, publishers and frequencies are copied exactly.
2. For each source, wrote coverage, format, key requirement and proposal matches by hand from the catalog description, its notes and general knowledge of the source. **The live sites were not opened one by one.**
3. "Updates (stated)" is the catalog's own frequency (`accrualPeriodicity`); the catalog gives no per-source dates.
4. On 2026-11-18, a read-only script requested every listed link once and recorded the HTTP result, any redirect, and the best date it could see. The date comes from the last commit (GitHub sources), the newest date in the data (XML files), or the server's Last-Modified header. A header date on a dynamic web page often shows only when the page was generated, so it is weak evidence. The script identified itself honestly, so sites that block automated requests are marked "not tested". Failures were re-checked by hand, including public DNS lookups for the sites that did not resolve.
5. Read all 20 proposal pages and the June 2026 priorities page. A source "could feed" a proposal when it holds data the proposal's own text asks for. Doc-only entries point to the source they document.

**Limits:** the matches are one person's judgment over two hours. "Covered" means the data exists somewhere on the list, not that it is easy to get. "Needs key" for #35 (GovInfo MCP) is unconfirmed. "Not reachable publicly" means the site's name doesn't resolve on the public internet. That fits a Congress-only network, but from outside it can't be told apart from a site that was shut down. The check covers only the link listed for each source, not every file behind it.

## Proposals and the sources that could feed them

Coverage: **Covered**, the list has the core data; **Partial**, some data is listed but a key input is missing; **Gap**, the main input is not on the list; **Not needed**, no data source is needed.

| Proposal | June 2026 status | Coverage | Sources | Not in the catalog |
|---|---|---|---|---|
| [I.1 Unified Congressional Hearing & Markup Data Platform](https://civictechdc.github.io/congressional-tech/proposals/I.1/) | Not discussed | Partial | 12: #5 #29 #34 #39 #43 #54 #55 #72 #76 #82 #106 #110 | House well covered (docs.house.gov); Senate has upcoming hearings only (#110), no hearing history or documents; committee YouTube channels not listed |
| [I.2 Committee YouTube Video Dashboard & Event ID Tracking](https://civictechdc.github.io/congressional-tech/proposals/I.2/) | Taken on by AGI (built) | Partial | 8: #5 #54 #55 #72 #76 #82 #106 #110 | YouTube Data API (committee channels) is not listed |
| [I.3 Statements of Disbursements as Structured Data](https://civictechdc.github.io/congressional-tech/proposals/I.3/) | Unclear | Partial | 4: #75 #86 #89 #104 | Pre-2009 House disbursement reports (e.g. Boston Public Library scans); listed House page covers 2009 onward, CSV only since 2016 |
| [I.4 Appropriations Data Pipeline & Historical Analysis](https://civictechdc.github.io/congressional-tech/proposals/I.4/) | Not discussed | Covered | 20: #6 #12 #13 #14 #20 #22 #29 #34 #36 #38 #39 #47 #49 #53 #55 #57 #59 #63 #77 #85 | Appropriations committee press releases and committee-stage amendments |
| [II.1 Automated Google Doc Creator for Meetings](https://civictechdc.github.io/congressional-tech/proposals/II.1/) | Not discussed | Not needed | 0 | No data source needed (Google Drive tool) |
| [II.2 GitHub Wiki Indexing Bookmarklet](https://civictechdc.github.io/congressional-tech/proposals/II.2/) | Not discussed | Not needed | 0 | No data source needed (browser tool) |
| [II.3 Crosswalk Spreadsheet to Member Office Appropriations Submission Tool](https://civictechdc.github.io/congressional-tech/proposals/II.3/) | Open target | Gap | 1: #87 | Each Member office's appropriations request form; directories give contacts only |
| [II.4 Floor Schedule to iCal & Enhanced Congressional Schedule Aggregation](https://civictechdc.github.io/congressional-tech/proposals/II.4/) | Open target | Partial | 12: #54 #55 #60 #68 #76 #77 #78 #85 #105 #110 #115 #116 | House floor and committees covered; no Senate floor schedule feed (the listed Senate calendar is session days only, and stale at 2025) |
| [II.5 Congressional Job Board Aggregator](https://civictechdc.github.io/congressional-tech/proposals/II.5/) | Open target | Partial | 4: #1 #65 #89 #116 | USAJOBS API and House Employment Bulletin as data; only general House/Senate home pages are listed |
| [III.1 CRS Report Accessibility & Integration](https://civictechdc.github.io/congressional-tech/proposals/III.1/) | Partly done | Covered | 4: #4 #7 #35 #55 | — |
| [III.2 GAO Report Transformation & Dissemination](https://civictechdc.github.io/congressional-tech/proposals/III.2/) | Not discussed | Covered | 4: #14 #17 #18 #19 | — |
| [III.3 Automated Committee Hearing Transcripts & Summaries](https://civictechdc.github.io/congressional-tech/proposals/III.3/) | Partly done | Partial | 5: #29 #39 #55 #76 #110 | Committee hearing video/audio (YouTube, committee sites); listed video is floor-only; Senate has no hearing history or documents |
| [III.4 Write My GovTrack Newsletter](https://civictechdc.github.io/congressional-tech/proposals/III.4/) | Taken on by AGI | Covered | 19: #20 #29 #35 #36 #39 #53 #55 #56 #60 #64 #68 #76 #77 #78 #84 #85 #110 #114 #115 | Congressional Record is reachable only through GovInfo (#29, #39); no dedicated entry |
| [III.5 Witness Database with Proceeding Links & Testimony Summarization](https://civictechdc.github.io/congressional-tech/proposals/III.5/) | Not happening (dropped) | Partial | 6: #19 #29 #39 #43 #55 #76 | House witness lists via docs.house.gov (#76) and the Congress.gov API; no Senate witness lists or testimony as structured data |
| [IV.1 Bills to Committee Referral Prediction](https://civictechdc.github.io/congressional-tech/proposals/IV.1/) | Needs our help | Covered | 14: #5 #20 #21 #22 #29 #38 #44 #55 #67 #68 #72 #82 #106 #107 | — |
| [IV.2 Bill Delay Tracker](https://civictechdc.github.io/congressional-tech/proposals/IV.2/) | Open target | Covered | 9: #20 #21 #22 #29 #36 #37 #38 #54 #55 | — |
| [IV.3 Appropriations Notices & Deadlines Tracker](https://civictechdc.github.io/congressional-tech/proposals/IV.3/) | Top priority | Gap | 4: #53 #72 #76 #110 | House and Senate Appropriations Committee and subcommittee pages, and their testimony-instruction PDFs, are not listed; listed sources give hearing dates only |
| [IV.4 Committee Funding Tracker & Visualization](https://civictechdc.github.io/congressional-tech/proposals/IV.4/) | Open target | Covered | 10: #22 #29 #38 #39 #55 #57 #59 #75 #86 #104 | — |
| [IV.5 Line Up CBJs and Appropriations Committee Report Language](https://civictechdc.github.io/congressional-tech/proposals/IV.5/) | Downstream / later | Covered | 9: #12 #13 #22 #29 #38 #39 #57 #59 #63 | — |
| [V.1 Google Sheets Inflation Calculator](https://civictechdc.github.io/congressional-tech/projects/) | Built (not in June notes) | Gap | 0 | Consumer Price Index (BLS); no inflation data is listed |

## Flags: stale, wrong, internal-only or limited

A flag marks any entry where the catalog or the 2026-11-18 link check gives a reason for caution: stale, broken or moved, wrong in the catalog, not public, limited, or of unclear upkeep. No source appears abandoned. Being blocked by the automated check is not a flag in itself; those 14 sites show "not tested" in the full table.

| # | Source | Flag |
|---|---|---|
| 2 | [Congressional District Shapefiles](https://www.census.gov/geographies/mapping-files/2023/geo/tiger-line-file.html) | Stale: points to 118th Congress files; its own note says look on data.gov for the 119th |
| 4 | [EveryCRSReport.com](https://www.everycrsreport.com) | Active (page updated 2026-11-18), but run by a civil-society group, not Congress (catalog links americalabs.org) |
| 5 | [United States Project](https://github.com/unitedstates) | Volunteer-maintained, but active: congress-legislators last updated 2026-11-15, congress scrapers 2026-10-03 |
| 8 | [CRS.gov](https://crs.gov) | Not public: congressional staff only |
| 12 | [USAspending.gov](https://www.usaspending.gov/) | Catalog download link points to oversight.gov, not USAspending |
| 13 | [Congressional Justifications (CBJs)](https://www.usaspending.gov/agency) | Catalog download link points to treasury.gov |
| 25 | [Congressionally Mandated Reports Submission Portal](https://www.gpo.gov/how-to-work-with-us/agency/congressionally-mandated-reports) | Submission portal, not a data source for the public |
| 31 | [GovInfo Bill Status GitHub Repository](https://github.com/usgpo/bill-status) | Quiet: repository last updated 2024-09-18 |
| 36 | [GovInfo RSS Feeds](https://www.govinfo.gov/feeds) | Only the 100 most recent entries per feed |
| 54 | [Congress.gov](https://congress.gov) | Use the API (#55) instead of scraping |
| 60 | [DomeWatch](https://domewatch.us) | Run by one party's caucus, not a neutral office |
| 66 | [U.S. Capitol Visitor Center](https://visitthecapitol.gov) | Catalog error: download link points to aoc.gov |
| 69 | [Congressional district maps](https://kml.house.gov) | Catalog error: described as shapefiles, but the files are KML |
| 75 | [House Committee Activity Reports (CHA)](https://cha.house.gov/committee-reports) | Broken link: catalog URL returns 404; the reports are now at https://cha.house.gov/member-services/monthly-reports (PDF) |
| 86 | [House Statement of Disbursements](https://www.house.gov/the-house-explained/open-government/statement-of-disbursements) | Web page goes back only to 2009; I.3 needs ~1980 onward |
| 88 | [House XML Resources](https://xml.house.gov) | Page last modified 2024-08-05; may no longer be maintained |
| 90 | [HouseCal](https://calendar.house.gov) | Not reachable from the public internet: the name does not resolve; catalog note calls it an internal feed |
| 91 | [HouseNet](https://housenet.house.gov) | Not public: House staff only (name does not resolve on the public internet) |
| 92 | [LegiDex](https://legidex.house.gov) | Not reachable from the public internet: the name does not resolve |
| 93 | [MemRec](https://memrec.house.gov) | Not a data source (a flash-card game), and not reachable from the public internet |
| 94 | [Office of Congressional Compliance](https://conduct.house.gov/) | Catalog name may be out of date; check the office's current name |
| 97 | [Civilian Pending in Committee](https://www.senate.gov/legislative/LIS/nominations/NomCivilianPendingCommittee.xml) | Catalog error: same URL as #102, and its description describes a different, discontinued collection (presidential documents 2009–2016) |
| 104 | [Report of the Secretary of the Senate](https://www.senate.gov/legislative/common/generic/report_secsen.htm) | PDF only; online since 2011 |
| 105 | [Senate annual Calendar](https://www.senate.gov/legislative/2025_schedule.xml) | Stale link: points to the 2025 calendar (no 2026 dates in it); a 2026 file exists at https://www.senate.gov/legislative/2026_schedule.xml |
| 109 | [Senate Floor Video](https://www.senate.gov/legislative/floor_activity_pail.htm) | No archive |
| 110 | [Senate Hearings XML](https://www.senate.gov/general/committee_schedules/hearings.xml) | Upcoming only; no history |
| 111 | [Senate Lobbying Disclosure](https://lda.senate.gov/system/public/) | Listed address returns 503 (Service Unavailable); the same system answers at https://lda.gov, so it has likely moved |
| 117 | [Webster](https://webster.senate.gov) | Not public: Senate staff only (not reachable from the public internet) |

## Sources that are not on the list but should be

The proposals need these sources, and the catalog doesn't list them. They are candidates to suggest to the Congressional Data Task Force:

- **House and Senate Appropriations Committee websites** ([appropriations.house.gov](https://appropriations.house.gov), [appropriations.senate.gov](https://www.appropriations.senate.gov)), including the subcommittee testimony instructions. These feed IV.3, the top priority, as well as II.3 and I.4.
- **A Senate committee proceedings source** with hearing history, documents and witness lists (the House equivalent is docs.house.gov, #76), and a **Senate floor schedule feed**. These would move I.1, II.4, III.3 and III.5 toward covered.
- **Committee YouTube channels** through the YouTube Data API, for I.2, I.1 and III.3.
- **USAJOBS API**, the **House Employment Bulletin** as data, and the **House GOP Job Bank** (listed on cha.house.gov), for II.5.
- **Historic House Statements of Disbursements** from before 2009, for I.3.
- **Consumer Price Index** from the Bureau of Labor Statistics, for V.1.
- **Congressional Record** as its own entry. Today it is reachable only inside GovInfo (#29, #39). It feeds III.4.

## All 119 sources

Key: "No" means open access. "Updates (stated)" is the catalog's own frequency. "Link check" and "Latest date seen" come from the 2026-11-18 check, and each date names its source. "—" means no proposal match, or no date found.

| # | Source | Run by | Covers | Format | Key? | Updates (stated) | Link check | Latest date seen | Could feed |
|---|---|---|---|---|---|---|---|---|---|
| 1 | [Architect of the Capitol](https://aoc.gov) | Architect of the Capitol | Capitol buildings, art, history; careers page links to USAJOBS | Web pages | No | irregular | OK (redirects) | 2026-11-19 (server header) | II.5 |
| 2 | [Congressional District Shapefiles](https://www.census.gov/geographies/mapping-files/2023/geo/tiger-line-file.html) | Census Bureau | Congressional district boundaries (118th Congress) | Bulk download (shapefiles) | No | irregular | OK | — | — |
| 3 | [My Congressional District](https://www.census.gov/mycd) | Census Bureau | Census demographic, economic and housing profiles by district | Web pages | No | irregular | OK | — | — |
| 4 | [EveryCRSReport.com](https://www.everycrsreport.com) | Civil Society | CRS reports, including old and superseded versions, with version comparison | Web pages; per-report HTML/PDF downloads | No | continuous | OK | 2026-11-18 (server header) | III.1 |
| 5 | [United States Project](https://github.com/unitedstates) | Civil Society | Volunteer tools and data: legislators, committees, scrapers (congress-legislators YAML/JSON/CSV) | GitHub repositories (bulk files) | No | continuous | OK | 2026-11-16 (last commit) | I.1, I.2, IV.1 |
| 6 | [CBO.gov](https://cbo.gov) | Congressional Budget Office | CBO cost estimates, budget projections, economic outlook | Web pages; PDF; spreadsheet downloads | No | continuous | Blocked automated check (403); not tested | — | I.4 |
| 7 | [Congressional Research Service Reports](https://www.congress.gov/crs-products) | Congressional Research Service | CRS reports and products published on Congress.gov | Web pages; Congress.gov API (CRS report endpoint) | Yes for API (free api.data.gov key) | irregular | Blocked automated check (403); not tested | — | III.1 |
| 8 | [CRS.gov](https://crs.gov) | Congressional Research Service | CRS website for Congress | Web pages (congressional network only) | Login (internal to Congress) | irregular | Error (522, no reason given) | — | — |
| 9 | [Copyright Office](https://www.copyright.gov) | Copyright Office | Copyright Office website | Web pages | No | irregular | OK | 2026-11-17 (server header) | — |
| 10 | [Oversight.gov](https://oversight.gov) | Council of the Inspectors General on Integrity and Efficiency | Inspector General reports across federal government (20+ years, some gaps) | Web pages; search | No | continuous | Blocked automated check (406); not tested | — | — |
| 11 | [CISA DotGov data](https://github.com/cisagov/dotgov-data) | Cybersecurity and Infrastructure Security Agency | Registered .gov domains | GitHub repository (CSV) | No | continuous | OK | 2026-11-18 (last commit) | — |
| 12 | [USAspending.gov](https://www.usaspending.gov/) | Department of Treasury | Federal spending: contracts, grants, loans, account balances | API; bulk download | No | continuous | OK | 2026-11-13 (server header) | I.4, IV.5 |
| 13 | [Congressional Justifications (CBJs)](https://www.usaspending.gov/agency) | Federal Agencies | Agency congressional budget justifications (CBJs), linked from one index | Web pages linking to agency PDFs | No | annual | OK | 2026-11-13 (server header) | IV.5, I.4 |
| 14 | [GAO appropriations decisions](https://www.gao.gov/legal/appropriations-law/search) | Government Accountability Office | GAO decisions and opinions on appropriations law | Web pages; search; PDF | No | irregular | OK | 2026-11-18 (server header) | III.2, I.4 |
| 15 | [GAO bid protests](https://www.gao.gov/legal/bid-protests/search) | Government Accountability Office | GAO decisions on contract bid protests | Web pages; search | No | irregular | OK | 2026-11-18 (server header) | — |
| 16 | [GAO Innovation Lab](https://innovations.gao.gov) | Government Accountability Office | GAO Innovation Lab project pages | Web pages | No | irregular | Blocked automated check (403); not tested | — | — |
| 17 | [GAO Legal Opinions](https://www.gao.gov/legal/other-legal-work/decisions-and-faqs) | Government Accountability Office | GAO legal decisions under statutory mandates or congressional request | Web pages; PDF | No | irregular | OK | 2026-11-18 (server header) | III.2 |
| 18 | [GAO Restricted Reports](https://www.gao.gov/reports-testimonies/restricted) | Government Accountability Office | Titles of GAO restricted reports, 2015–present | Web pages (table) | No | irregular | OK | 2026-11-18 (server header) | III.2 |
| 19 | [GAO.gov](https://gao.gov) | Government Accountability Office | GAO reports, testimonies, legal decisions | Web pages; PDF; RSS | No | continuous | OK (redirects) | 2026-11-18 (server header) | III.2, III.5 |
| 20 | [Bill Status XML Bulk Data](https://www.govinfo.gov/bulkdata/BILLSTATUS) | Government Publishing Office | Bill status: actions, committee referrals, sponsors, subjects, dates | Bulk download (XML) | No | daily | OK | — | IV.1, IV.2, I.4, III.4 |
| 21 | [Bill Summary XML Bulk Data](https://www.govinfo.gov/bulkdata/BILLSUM) | Government Publishing Office | CRS bill summaries with dates | Bulk download (XML) | No | daily | OK | — | IV.2, IV.1 |
| 22 | [Bill Text XML Bulk Data](https://www.govinfo.gov/bulkdata/BILLS) | Government Publishing Office | Full text of every bill version | Bulk download (XML) | No | daily | OK | — | IV.1, IV.2, I.4, IV.4, IV.5 |
| 23 | [Catalog of U.S. Government Publications](https://catalog.gpo.gov) | Government Publishing Office | Catalog of federal publications with links | Web search; MARC records | No | daily | Blocked automated check (403); not tested | — | — |
| 24 | [Code of Federal Regulations XML Bulk Data](https://www.govinfo.gov/bulkdata/CFR) | Government Publishing Office | Code of Federal Regulations, annual edition | Bulk download (XML) | No | annual | OK | — | — |
| 25 | [Congressionally Mandated Reports Submission Portal](https://www.gpo.gov/how-to-work-with-us/agency/congressionally-mandated-reports) | Government Publishing Office | Portal where agencies submit congressionally mandated reports (reports themselves on GovInfo) | Web portal (agency submission) | Agency account to submit | irregular | OK | 2026-11-19 (server header) | — |
| 26 | [eCFR XML Bulk Data](https://www.govinfo.gov/bulkdata/ECFR) | Government Publishing Office | Electronic CFR, updated daily (unofficial) | Bulk download (XML) | No | daily | OK | — | — |
| 27 | [Federal Register XML Bulk Data](https://www.govinfo.gov/bulkdata/FR) | Government Publishing Office | Federal Register: rules, notices, presidential documents | Bulk download (XML) | No | daily | OK | — | — |
| 28 | [Government Manual XML Bulk Data](https://www.govinfo.gov/bulkdata/GOVMAN) | Government Publishing Office | U.S. Government Manual: organization of all three branches | Bulk download (XML) | No | irregular | OK | — | — |
| 29 | [GovInfo API](https://api.govinfo.gov/docs/) | Government Publishing Office | API over all GovInfo collections: bills, reports, hearings, Congressional Record | API | Yes (free api.data.gov key) | daily | OK | 2026-09-09 (server header) | I.1, I.4, III.3, III.4, III.5, IV.1, IV.2, IV.4, IV.5 |
| 30 | [GovInfo API GitHub Repository](https://github.com/usgpo/api) | Government Publishing Office | Documentation, code samples and issues for the GovInfo API and MCP server | GitHub repository (documentation) | No | irregular | OK | 2026-07-21 (last commit) | — (docs for #29, #35) |
| 31 | [GovInfo Bill Status GitHub Repository](https://github.com/usgpo/bill-status) | Government Publishing Office | User guide for Bill Status XML | GitHub repository (documentation) | No | irregular | OK | 2024-09-18 (last commit) | — (docs for #20) |
| 32 | [GovInfo Bulk Data GitHub Repository](https://github.com/usgpo/bulk-data) | Government Publishing Office | User guides for GovInfo bulk data | GitHub repository (documentation) | No | irregular | OK | 2026-06-11 (last commit) | — (docs for #38) |
| 33 | [GovInfo Developer Hub](https://www.govinfo.gov/developers) | Government Publishing Office | Developer landing page for GovInfo | Web pages (documentation) | No | irregular | OK | 2026-11-18 (server header) | — (docs for #29, #38) |
| 34 | [GovInfo Link Service](https://www.govinfo.gov/link-docs) | Government Publishing Office | Stable, predictable links to GovInfo documents and metadata | Link service (URL patterns) | No | continuous | OK | 2026-09-09 (server header) | I.1, I.4 |
| 35 | [GovInfo MCP Server](https://github.com/usgpo/api/blob/main/docs/mcp.md) | Government Publishing Office | Model Context Protocol server so AI tools can query GovInfo | MCP server (API) | Likely yes (uses GovInfo API key) | irregular | OK | 2026-07-21 (last commit) | III.4, III.1 |
| 36 | [GovInfo RSS Feeds](https://www.govinfo.gov/feeds) | Government Publishing Office | RSS feeds of new items per GovInfo collection (100 most recent) | RSS | No | continuous | OK | 2026-11-18 (server header) | IV.2, III.4, I.4 |
| 37 | [GovInfo Sitemaps](https://www.govinfo.gov/sitemaps) | Government Publishing Office | XML sitemaps with last-modified dates for every GovInfo item | XML sitemaps | No | continuous | OK | 2026-11-18 (server header) | IV.2 |
| 38 | [GovInfo XML Bulk Data Repository](https://www.govinfo.gov/bulkdata) | Government Publishing Office | Bulk XML for bills, bill status, summaries, laws, statutes, CFR, FR and more | Bulk download (XML/ZIP) | No | daily | OK | — | I.4, IV.1, IV.2, IV.4, IV.5 |
| 39 | [GovInfo.gov](https://www.govinfo.gov) | Government Publishing Office | Official publications of all three branches: Congressional Record, hearings, reports, bills | Web pages; PDF; text; XML | No (API needs key) | continuous | OK | 2026-11-18 (server header) | I.1, I.4, III.3, III.4, III.5, IV.4, IV.5 |
| 40 | [GPO Cataloging Records GitHub Repository](https://github.com/usgpo/cataloging-records) | Government Publishing Office | GPO bibliographic records | GitHub repository (MARC, MARC XML) | No | irregular | OK | 2026-10-20 (last commit) | — |
| 41 | [GPO GitHub Organization](https://github.com/usgpo) | Government Publishing Office | All GPO GitHub repositories | GitHub organization | No | continuous | OK | 2026-11-17 (last commit) | — (index of #30–32, #40, #50) |
| 42 | [GPO.gov](https://www.gpo.gov) | Government Publishing Office | GPO corporate website | Web pages | No | daily | OK | 2026-11-18 (server header) | — |
| 43 | [House Committee Activity Reports (GPO)](https://www.govinfo.gov/app/search/%7B%22query%22%3A%22doctype%3A(HRPT)%20AND%20title%3A(Activity%20Report)%22%2C%22offset%22%3A0%7D) | Government Publishing Office | End-of-Congress House committee activity reports | Web pages; PDF; text (via GovInfo search) | No | biennial | OK | 2026-09-23 (server header) | I.1, III.5 |
| 44 | [House Rules and Manual XML Bulk Data](https://www.govinfo.gov/bulkdata/HMAN) | Government Publishing Office | House Rules and Jefferson's Manual, incl. Rule X committee jurisdiction | Bulk download (XML) | No | biennial | OK | — | IV.1 |
| 45 | [Innovation Hub](https://usgpo.github.io/innovation/) | Government Publishing Office | This catalog: Congressional Data Task Force hub | Web pages; DCAT JSON (data.json) | No | irregular | OK | 2026-11-17 (server header) | — (this catalog) |
| 46 | [Privacy Act Issuances XML Bulk Data](https://www.govinfo.gov/bulkdata/PAI) | Government Publishing Office | Privacy Act system-of-records notices | Bulk download (XML) | No | biennial | OK | — | — |
| 47 | [Public and Private Laws XML Bulk Data](https://www.govinfo.gov/bulkdata/PLAW) | Government Publishing Office | Slip laws (public and private laws) | Bulk download (XML) | No | irregular | OK | — | I.4 |
| 48 | [Statute Compilations XML Bulk Data](https://www.govinfo.gov/bulkdata/COMPS) | Government Publishing Office | House Legislative Counsel statute compilations | Bulk download (XML) | No | weekly | OK | — | — |
| 49 | [Statutes at Large XML Bulk Data](https://www.govinfo.gov/bulkdata/STATUTE) | Government Publishing Office | Statutes at Large | Bulk download (XML) | No | irregular | OK | — | I.4 |
| 50 | [USLM GitHub Repository](https://github.com/usgpo/uslm) | Government Publishing Office | United States Legislative Markup (USLM) schemas and guides | GitHub repository (documentation) | No | irregular | OK | 2026-10-14 (last commit) | — (schema for #22, #47, #62) |
| 51 | [Law Library of Congress](https://www.loc.gov/research-centers/law-library-of-congress/about-this-research-center/) | Law Library of Congress | Law Library of Congress research services | Web pages | No | irregular | Blocked automated check (403); not tested | — | — |
| 52 | [Law Library of Congress Legal Reports](https://www.loc.gov/research-centers/law-library-of-congress/legal-reports/) | Law Library of Congress | Law Library reports on foreign and comparative law | Web pages; PDF | No | irregular | Blocked automated check (403); not tested | — | — |
| 53 | [Appropriations Status Table](https://crsreports.congress.gov/AppropriationsStatusTable) | Library of Congress | Status of each regular, continuing and supplemental appropriations bill | Web pages (table) | No | irregular | Blocked automated check (403); not tested | — | I.4, IV.3, III.4 |
| 54 | [Congress.gov](https://congress.gov) | Library of Congress | Official legislative information website | Web pages | No | continuous | Blocked automated check (403); not tested | — | I.1, I.2, II.4, IV.2 |
| 55 | [Congress.gov API](https://api.congress.gov) | Library of Congress | API over Congress.gov: bills, committees, committee meetings (event IDs, witnesses), hearings, reports, CRS reports, nominations | API | Yes (free api.data.gov key) | continuous | OK | 2026-11-19 (server header) | I.1, I.2, I.4, II.4, III.1, III.3, III.4, III.5, IV.1, IV.2, IV.4 |
| 56 | [Executive Reports](https://www.congress.gov/executive-reports) | Library of Congress | Committee reports on treaties and nominations | Web pages | No | continuous | Blocked automated check (403); not tested | — | III.4 |
| 57 | [House Committee Reports](https://www.congress.gov/house-reports) | Library of Congress | House committee reports, incl. appropriations reports | Web pages; PDF; text (also in API) | No | continuous | Blocked automated check (403); not tested | — | I.4, IV.5, IV.4 |
| 58 | [LOC.gov](https://loc.gov) | Library of Congress | Library of Congress website and collections | Web pages; loc.gov JSON API | No | continuous | OK (redirects) | — | — |
| 59 | [Senate Committee Reports](https://www.congress.gov/senate-reports) | Library of Congress | Senate committee reports, incl. appropriations reports | Web pages; PDF; text (also in API) | No | continuous | Blocked automated check (403); not tested | — | I.4, IV.5, IV.4 |
| 60 | [DomeWatch](https://domewatch.us) | Member of Congress | House floor schedule and votes (House Democrats' app) | Web app | No | daily | OK | — | II.4, III.4 |
| 61 | [Office of Congressional Workplace Rights](https://www.ocwr.gov/) | Office of Congressional Workplace Rights | Workplace rights, safety and accessibility in the legislative branch | Web pages | No | irregular | OK | 2026-11-18 (server header) | — |
| 62 | [United States Code](https://uscode.house.gov) | Office of Law Revision Counsel | U.S. Code with classification tables | Web pages; bulk download (USLM XML) | No | irregular | OK | 2026-11-13 (server header) | — |
| 63 | [President's Budget Appendix](https://www.whitehouse.gov/omb/budget) | Office of Management and Budget | President's budget and appendix: requested funding and language | Web pages; PDF; spreadsheets | No | annual | OK (redirects) | — | IV.5, I.4 |
| 64 | [PLUM Reporting Website](https://www.opm.gov/about-us/open-government/plum-reporting/) | Office of Personnel Management | Political appointees and senior positions (PLUM list) | Web pages; data download | No | annual | OK | — | III.4 |
| 65 | [U.S. Capitol Police](https://www.uscp.gov/) | U.S. Capitol Police | Capitol Police website, incl. arrest data and careers | Web pages | No | irregular | OK | — | II.5 |
| 66 | [U.S. Capitol Visitor Center](https://visitthecapitol.gov) | U.S. Capitol Visitor Center | Capitol tours and visitor services | Web pages | No | irregular | OK (redirects) | — | — |
| 67 | [Bioguide](https://bioguide.congress.gov) | U.S. House of Representatives | Biographies of all past and present Members | Web pages; data download | No | irregular | Blocked automated check (403); not tested | — | IV.1 |
| 68 | [Clerk.House.gov](https://clerk.house.gov) | U.S. House of Representatives | House roll calls, floor proceedings, member and committee info | Web pages; XML | No | continuous | OK | — | II.4, III.4, IV.1 |
| 69 | [Congressional district maps](https://kml.house.gov) | U.S. House of Representatives | Congressional district maps | Bulk download (KML) | No | irregular | OK | 2026-04-01 (server header) | — |
| 70 | [House Clerk Financial Disclosure Reports](https://disclosures-clerk.house.gov/FinancialDisclosure) | U.S. House of Representatives | House Member and candidate financial disclosures | Web search; ZIP downloads; PDF | No | daily | OK | — | — |
| 71 | [House Clerk Foreign Travel Reports](https://disclosures-clerk.house.gov/ForeignTravel) | U.S. House of Representatives | House Member foreign travel reports | Web pages; PDF | No | daily | OK | — | — |
| 72 | [House Clerk Member Data XML](https://clerk.house.gov/xml/lists/MemberData.xml) | U.S. House of Representatives | House Members with BioGuide IDs, committee and subcommittee codes | XML file | No | monthly | OK | 2026-11-03 (server header) | I.1, I.2, IV.1, IV.3 |
| 73 | [House Clerk Private Sponsor Travel Filings](https://disclosures-clerk.house.gov/GiftTravelFilings) | U.S. House of Representatives | House privately sponsored travel disclosures | Web search; PDF | No | annual | OK | — | — |
| 74 | [House Clerk Unsolicited Mass Communications](https://masscommsdisclosure.house.gov/) | U.S. House of Representatives | House Members' mass mailings (franking) | Web search; PDF | No | daily | OK | — | — |
| 75 | [House Committee Activity Reports (CHA)](https://cha.house.gov/committee-reports) | U.S. House of Representatives | Monthly House committee expenditures, activities and staffing | PDF | No | monthly | Broken (404) | — | IV.4, I.3 |
| 76 | [House Committee Repository](https://docs.house.gov/committee) | U.S. House of Representatives | All House committee meetings: event IDs, notices, witnesses, testimony, documents | Web pages; XML feeds | No | daily | OK (redirects) | — | I.1, I.2, II.4, III.3, III.4, III.5, IV.3 |
| 77 | [House Floor Bills Repository](https://docs.house.gov/floor) | U.S. House of Representatives | Weekly House floor schedule with bill text and Rules Committee prints | Web pages; XML | No | continuous | OK | — | II.4, III.4, I.4 |
| 78 | [House Floor Summary](https://clerk.house.gov/floorsummary/floor-download.aspx) | U.S. House of Representatives | Timestamped chronology of House floor actions | XML download; RSS | No | continuous | OK (redirects) | — | II.4, III.4 |
| 79 | [House History](https://history.house.gov) | U.S. House of Representatives | House history tables: party divisions, session dates, oral histories | Web pages (tables) | No | irregular | OK | — | — |
| 80 | [House Live Video](https://live.house.gov) | U.S. House of Representatives | Live House floor video | Video stream | No | continuous | OK | 2026-10-21 (server header) | — |
| 81 | [House Lobbying Disclosure](https://lobbyingdisclosure.house.gov/) | U.S. House of Representatives | House lobbying registrations and reports | Web search; XML downloads | No | continuous | OK | 2026-10-13 (server header) | — |
| 82 | [House Member Information XML](https://member-info.house.gov/members.xml) | U.S. House of Representatives | House Members: contact, BioGuide ID, photo, social media, committees | XML file | No | daily | OK | 2026-11-18 (newest record in file) | I.1, I.2, IV.1 |
| 83 | [House Post-Employment Lobbying Disclosures](https://disclosures-clerk.house.gov/PostEmploymentNotification) | U.S. House of Representatives | Post-employment lobbying restrictions for former House staff | Web pages; download | No | irregular | OK | — | — |
| 84 | [House Roll Call Votes](https://clerk.house.gov/Votes) | U.S. House of Representatives | House roll call votes with each Member's vote (BioGuide IDs) | Web pages; XML | No | continuous | OK | — | III.4 |
| 85 | [House Rules Committee](https://rules.house.gov) | U.S. House of Representatives | Bills headed to the House floor, amendments offered, Rules schedule | Web pages; documents | No | irregular | OK | — | I.4, II.4, III.4 |
| 86 | [House Statement of Disbursements](https://www.house.gov/the-house-explained/open-government/statement-of-disbursements) | U.S. House of Representatives | Spending by House Members, committees, leadership and officers | CSV (since 2016); PDF | No | quarterly | OK | 2026-11-19 (server header) | I.3, IV.4 |
| 87 | [House Telephone Directory](https://directory.house.gov) | U.S. House of Representatives | House staff and Member contact directory | Web pages; export | No | irregular | OK | — | II.3 |
| 88 | [House XML Resources](https://xml.house.gov) | U.S. House of Representatives | House XML standards, DTDs and presentations | Web pages (documentation) | No | irregular | OK | 2024-08-05 (server header) | — (docs for #22, #77) |
| 89 | [House.gov](https://house.gov) | U.S. House of Representatives | House home page, incl. employment bulletin and disbursements pages | Web pages | No | continuous | OK (redirects) | 2026-11-19 (server header) | II.5, I.3 |
| 90 | [HouseCal](https://calendar.house.gov) | U.S. House of Representatives | House central calendar of floor and committee activity | Web pages (calendar) | Not public (House network only, apparently) | continuous | Not reachable publicly (name does not resolve) | — | — |
| 91 | [HouseNet](https://housenet.house.gov) | U.S. House of Representatives | House intranet | Web pages (internal) | Login (House staff only) | irregular | Not reachable publicly (name does not resolve) | — | — |
| 92 | [LegiDex](https://legidex.house.gov) | U.S. House of Representatives | House staff directory with policy roles | Web pages (directory) | Not public (House network only, apparently) | daily | Not reachable publicly (name does not resolve) | — | — |
| 93 | [MemRec](https://memrec.house.gov) | U.S. House of Representatives | Member flash-card game; source of Member photos | Web app | No | continuous | Not reachable publicly (name does not resolve) | — | — |
| 94 | [Office of Congressional Compliance](https://conduct.house.gov/) | U.S. House of Representatives | House ethics office: investigation status, quarterly reports | Web pages | No | irregular | OK | — | — |
| 95 | [Civilian Nomination Confirmed](https://www.senate.gov/legislative/LIS/nominations/NomCivilianConfirmed.xml) | U.S. Senate | Confirmed civilian nominations | XML feed | No | daily | OK | 2026-11-17 (newest record in file) | — |
| 96 | [Civilian Nomination Pending on Calendar](https://www.senate.gov/legislative/LIS/nominations/NomCivilianPendingCalendar.xml) | U.S. Senate | Civilian nominations pending on the Senate calendar | XML feed | No | daily | OK | 2026-11-17 (newest record in file) | — |
| 97 | [Civilian Pending in Committee](https://www.senate.gov/legislative/LIS/nominations/NomCivilianPendingCommittee.xml) | U.S. Senate | Listed as civilian nominations pending in committee | XML feed | No | daily | OK | 2026-11-17 (newest record in file) | — |
| 98 | [Failed and Returned Nominations](https://www.senate.gov/legislative/LIS/nominations/NomFailedOrReturned.xml) | U.S. Senate | Failed and returned nominations | XML feed | No | daily | OK | 2026-01-03 (newest record in file) | — |
| 99 | [Military Nomination Confirmed](https://www.senate.gov/legislative/LIS/nominations/NomNonCivilianConfirmed.xml) | U.S. Senate | Confirmed military nominations | XML feed | No | daily | OK | 2026-11-12 (newest record in file) | — |
| 100 | [Military Nomination Pending in Committee](https://www.senate.gov/legislative/LIS/nominations/NomNonCivilianPendingCommittee.xml) | U.S. Senate | Military nominations pending in committee | XML feed | No | daily | OK | 2026-11-16 (newest record in file) | — |
| 101 | [Military Nomination Pending on Calendar](https://www.senate.gov/legislative/LIS/nominations/NomNonCivilianPendingCalendar.xml) | U.S. Senate | Military nominations pending on the Senate calendar | XML feed | No | daily | OK | 2026-11-10 (newest record in file) | — |
| 102 | [Pending Civilian Nominations](https://www.senate.gov/legislative/LIS/nominations/NomCivilianPendingCommittee.xml) | U.S. Senate | Civilian nominations pending in committee, with committee IDs and referral dates | XML feed | No | daily | OK | 2026-11-17 (newest record in file) | — |
| 103 | [Privileged Nominations](https://www.senate.gov/legislative/LIS/nominations/NomPrivileged.xml) | U.S. Senate | Privileged nominations pending in committee | XML feed | No | daily | OK | 2026-11-10 (newest record in file) | — |
| 104 | [Report of the Secretary of the Senate](https://www.senate.gov/legislative/common/generic/report_secsen.htm) | U.S. Senate | Senate spending by Senators, committees and officers | PDF | No | irregular | OK | — | IV.4, I.3 |
| 105 | [Senate annual Calendar](https://www.senate.gov/legislative/2025_schedule.xml) | U.S. Senate | Senate session days, state work periods and holidays | XML file | No | annual | OK | 2025-12-31 (newest record in file) | II.4 |
| 106 | [Senate Committee Information XML](https://www.senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml) | U.S. Senate | Senators with committee assignments, IDs, BioGuide–LIS crosswalk | XML file | No | daily | OK | 2026-11-18 (server header) | I.1, I.2, IV.1 |
| 107 | [Senate Contact Information XML](https://www.senate.gov/general/contact_information/senators_cfm.xml) | U.S. Senate | Current Senators: name, party, state, BioGuide ID | XML file | No | biennial | OK | 2026-11-18 (newest record in file) | IV.1 |
| 108 | [Senate Financial Disclosure Reports](https://efdsearch.senate.gov/search/home/) | U.S. Senate | Senator and candidate financial disclosures | Web search | No (accept terms) | daily | OK | — | — |
| 109 | [Senate Floor Video](https://www.senate.gov/legislative/floor_activity_pail.htm) | U.S. Senate | Live Senate floor video, no archive | Video stream | No | continuous | OK | — | — |
| 110 | [Senate Hearings XML](https://www.senate.gov/general/committee_schedules/hearings.xml) | U.S. Senate | Upcoming Senate committee hearings with committee IDs | XML feed | No | daily | OK | 2026-11-18 (newest record in file) | I.1, I.2, II.4, III.3, III.4, IV.3 |
| 111 | [Senate Lobbying Disclosure](https://lda.senate.gov/system/public/) | U.S. Senate | Senate lobbying registrations and reports | API; web search; downloads | Optional (free key raises rate limit) | daily | Error (503, Service Unavailable) | — | — |
| 112 | [Senate Post Employment Lobbying Disclosure](https://www.senate.gov/pagelayout/legislative/g_three_sections_with_teasers/lobbyingdisc.htm) | U.S. Senate | Post-employment lobbying restrictions for former Senate staff | Web pages (one very large HTML table) | No | annual | OK | — | — |
| 113 | [Senate Private Sponsor Travel Filings](https://giftrule-disclosure.senate.gov/) | U.S. Senate | Senate privately sponsored travel disclosures | Web search | No | daily | Blocked automated check (403); not tested | — | — |
| 114 | [Senate Roll Call Votes](https://www.senate.gov/legislative/votes_new.htm) | U.S. Senate | Senate roll call votes (LIS IDs, not BioGuide) | Web pages; XML | No | continuous | OK | — | III.4 |
| 115 | [Senate XML Resources](https://www.senate.gov/general/XML.htm) | U.S. Senate | Index of Senate XML and HTML data | Web pages (index) | No | irregular | OK | — | II.4, III.4 |
| 116 | [Senate.gov](https://senate.gov) | U.S. Senate | Senate home page, incl. floor schedule and employment bulletin | Web pages | No | continuous | OK (redirects) | — | II.4, II.5 |
| 117 | [Webster](https://webster.senate.gov) | U.S. Senate | Senate intranet | Web pages (internal) | Login (Senate staff only) | irregular | Not reachable publicly (name does not resolve) | — | — |
| 118 | [Withdrawn Nominations](https://www.senate.gov/legislative/LIS/nominations/NomWithdrawn.xml) | U.S. Senate | Withdrawn nominations | XML feed | No | daily | OK | 2026-11-10 (newest record in file) | — |
| 119 | [Congressional Pictorial Directory](https://www.govinfo.gov/collection/congressional-pictorial-directory) | Government Publishing Office | Photos of every Member and officer, per Congress | PDF (via GovInfo) | No | biennial | OK | 2026-11-18 (server header) | — |
