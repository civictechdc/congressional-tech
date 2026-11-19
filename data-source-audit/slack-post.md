# Draft post for #congressional-tech (or a GitHub issue)

Draft only; not posted. Suggested issue title: **Data source audit: which GPO-listed sources feed our proposals, and the gaps**

---

At the June meeting with the American Governance Institute, one action item was to audit the data sources on GPO's Innovation Hub so new projects reuse what exists. Here's a first pass from tonight's meetup.

**What we did:** matched all 119 sources on https://usgpo.github.io/innovation/data against our 20 proposals (19 open plus the built Inflation Calculator), recording who runs each source, its format, whether it needs a key, and its stated update frequency.

**What we found**
- A few sources do most of the work. The Congress.gov API feeds 11 proposals and GovInfo feeds 9. docs.house.gov and the Senate Hearings XML each feed 6–7 more. 56 of the 119 sources feed at least one proposal, and 107 are open with no key.
- The top June priority is a gap. The Appropriations Deadlines Tracker (IV.3) needs the House and Senate Appropriations Committee pages and their testimony-instruction PDFs, and neither is on the list. Also uncovered: II.3 (Member office request forms) and V.1 (inflation/CPI data).
- The Senate is the recurring gap. There's no Senate hearing history, no witness lists and no floor schedule feed, so I.1, II.4, III.3 and III.5 are only partly covered. Also partial: I.2 (committee YouTube), II.5 (USAJOBS) and I.3 (disbursements before 2009).
- No source looks abandoned. The list has no per-source "last updated" field, so we checked every link on Nov 18. The core data feeds are current, with nominations, hearings and member files updated this week. Two links are broken or moved: the House Administration committee reports now live at cha.house.gov/member-services/monthly-reports, and Senate lobbying now answers at lda.gov. Six listed sites (HouseCal, LegiDex, HouseNet, Webster, MemRec, CRS.gov) aren't reachable from the public internet. 14 sites, including Congress.gov pages, blocked the automated check, so they're untested. We flagged 28 entries in all, including a 2025 Senate calendar link (a 2026 file exists), a duplicated nominations URL with the wrong description, and download links pointing to the wrong sites.

**What it means:** new projects can start from a shared toolkit (Congress.gov API, GovInfo, docs.house.gov, Senate XML) instead of writing scrapers. IV.3 will need its own scraper. A Senate equivalent of docs.house.gov would unblock four proposals at once. The missing sources, a "last updated" field and the catalog fixes are worth sending to the Congressional Data Task Force.

**Next steps (help welcome):** have someone who knows each source review the matches; hand-check the 14 sites that blocked the automated check; send the catalog fixes to GPO.

June 2026 priorities: https://congressional-tech-backlog.netlify.app/updated-priorities
Full audit (table + CSV): <link to data-source-audit/ once pushed>
