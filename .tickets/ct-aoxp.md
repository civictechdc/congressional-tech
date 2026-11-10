---
id: ct-aoxp
status: in_progress
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 2
assignee: mikewolfd
tags: [model, record-roles, meetings]
---
# docs.house.gov/committee/Help.aspx is published as a document of 81 meetings

Newly captured House meeting pages link the site's help page, and the model publishes it as a document of 81 meetings; it accounts for 81 of the 105 document-count rises in meeting_coverage on 2026-11-10. It is site furniture, the same family of rule as ct-m878 (GovInfo landing pages). Source: .cache/archive-release/release-20261110/causes/video/README.md (coverage section).

## Acceptance Criteria

The help page has role wrapper (or is excluded) and is a document of no meeting; a scan lists other addresses that are a document of more than N meetings with a non-document path, with the count before and after.


## Notes

**2026-11-10T13:27:30Z**

2026-11-10 status: fixed on the stacked next-release branch claude/ct-next-release (commits 672bf44a test, 787ea6d7 fix: the help page is a wrapper through registry kind wrapper_url). Lanes green on the source branch (six shards + storage-loopback). Left: lanes and a full model build on the stack, the one review, release. Closes when released.
**2026-11-10T08:48:53Z**

Rule (branch claude/ct-document-roles: tests e3ab5231, fix 33ebc444; not merged, not built). page-signals gains kind `wrapper_url`, an address whose page only leads elsewhere, with one entry: a help page file (`help.aspx`, `help.html`, `help.php`, `help.cfm`) on any host. locator-signals judges the address that answered; record-roles gives the page role `wrapper`, so it is not a real file and makes no document.

How the 81 meetings arose: the Repository's chrome links Help from every page, including the error page it serves at a missing meeting file's address. That address names a meeting, so the link carried it. All 81 came through 133 such error pages.

Measured on release 619db5f9e08e. Scripts and outputs: `.cache/archive-release/investigations/document-roles-20261110/` (`dr-40-roles.out`, `dr-09-aoxp-effect.out`).

- The committed role SQL through the pinned engine on all 4,176,147 capture rows: before the change it gives back the exported record_roles exactly; after it, 2 rows change (the help page's two bodies, `document` to `wrapper`) and no other.
- Leaves the release: row 286993, its 2 link keys (58f225d644ab9ad0, c0a3d1b8b7c817ec; published first last night, so they retire to a removal notice with no successor, which is right for a help page), 1 address row, 1 lookup key. Each of the 81 meetings keeps at least one other document, so no coverage state changes, only counts (minus one each).
- The scan the ticket asks for, web-page documents by meeting count, before / after: 2 or more meetings 13 / 12; 5 or more 2 / 1; 14 or more 1 / 0. Every one left is a printed hearing's HTML text (`published-hearing`), the largest with 13 meetings.

Alternatives weighed on the same rows:

- Take no meeting from the address of an error page: the 81 meetings go, but the help page stays a document. No other document changes: on this release every meeting taken from a linking page's address came from an error page (133 pages; their only other target is the error page itself, 816 bodies, never a document). Worth doing as a second guard in source-annotations-addresses.sql; not done here, it is outside the role files and after this change it moves no row.
- Any web page linked from more than 100 pages is furniture (the placeholder rule's k): removes the help page and 21 other navigation pages (GovInfo's home page, linked from 35,363 pages; committee calendar and hearing indexes). A threshold flips live documents in and out as captures grow, and needs a new aggregate over 1.98M links before roles.
- Every Repository application page but the meeting pages: the help page plus 6 navigation pages (Committees.aspx 2, ByWeek 2, ByMonth 1, the home page 1), all with no meeting. A one-host URL list; left for the wider question below.

Found, not fixed: 48 web-page documents are linked from 30 or more captured pages (22 from 100 or more), and 8 documents are a site's home page. Only the help page has a meeting. They are navigation published as documents (`dr-05b-web-pages-linked-from-10-or-more.csv`; from 10 pages up the list also holds 23 parts of one printed hearing, which are real). A general furniture rule needs its own ticket and an owner view on which index pages are documents.

A full model build must confirm: no row for Help.aspx in list, links, sources or urls; its two keys in retired_links with no successor; `documents` counts of the 81 meetings each one lower; no other record_role changed.
