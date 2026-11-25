# Congressional data source audit

## Project

**Data source audit, Congressional Tech (Civic Tech DC).** A new action item from the [June 2026 priorities](https://congressional-tech-backlog.netlify.app/updated-priorities) set with the American Governance Institute: "we absolutely must audit their data sources" on the GPO Innovation Hub, so new projects reuse what already exists. Top June priorities: the Appropriations Deadlines Tracker (IV.3), Referral Prediction (IV.1) and Bill Delay Tracking (IV.2).

## Question

Which of the 119 legislative-branch data sources GPO lists could feed each of our 20 proposals, and where are the gaps?

## What we found

- **Five sources carry most of the work:** the Congress.gov API, the GovInfo API and bulk data, docs.house.gov and the Senate Hearings XML. 56 of the 119 sources feed at least one proposal, and 107 are open with no key.
- **The top June priority isn't covered, and the Senate is the recurring gap:** the Appropriations Committee pages and testimony-instruction PDFs behind the Deadlines Tracker (IV.3) are not on the list. The Senate has no hearing history, witness lists or floor schedule feed, which leaves four more proposals partly covered.
- **No source looks abandoned, but the list needs upkeep:** a check of every link on Nov 18 found the core data feeds current. Two links are broken or moved (House Administration reports, Senate lobbying now at lda.gov), and six sites aren't public. 28 entries in all are flagged as stale, wrong or not public, including a 2025 Senate calendar link and a duplicated URL with the wrong description.

## Sources

- GPO Innovation Hub, Data tab: https://usgpo.github.io/innovation/data ([data.json](https://usgpo.github.io/innovation/data.json); [source on GitHub](https://github.com/usgpo/innovation/blob/master/_data/data.json))
- Congressional Tech proposals: https://civictechdc.github.io/congressional-tech/proposals/
- June 2026 priorities: https://congressional-tech-backlog.netlify.app/updated-priorities
- Full audit: `data-source-audit.md` and `data-sources.csv` in this folder

## What it means for the project

New projects can start from a short, shared toolkit (Congress.gov API, GovInfo, docs.house.gov, Senate XML) instead of building their own scrapers. The top-priority Deadlines Tracker still needs its own scraper of the appropriations committee pages. A Senate counterpart to docs.house.gov would unblock four proposals at once. Those sources, plus YouTube, USAJOBS, CPI, a per-source "last updated" field and the catalog fixes, are worth sending to the Congressional Data Task Force.

## Built by

<!-- to fill in -->
