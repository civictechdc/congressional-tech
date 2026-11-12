---
id: ct-xj8s
status: closed
deps: []
links: []
created: 2026-11-10T20:37:59Z
type: task
priority: 3
assignee: mikewolfd
tags: [model, record-roles]
---
# Navigation pages published as documents: 48 web pages linked from 30 or more captured pages

Split from ct-aoxp when it closed on release 77673bfb8fcf (2026-11-10); its 08:48Z note said a general furniture rule needs its own ticket and an owner view. Measured then on 619db5f9e08e (.cache/archive-release/investigations/document-roles-20261110/dr-05b-web-pages-linked-from-10-or-more.csv): 48 web-page documents are linked from 30 or more captured pages (22 from 100 or more), and 8 documents are a site's home page; none has a meeting now that the help page is a wrapper. From 10 pages up the list also holds 23 parts of one printed hearing, which are real. Options weighed in ct-aoxp: a link-count threshold (flips documents as captures grow), or a per-host list of application pages.

## Acceptance Criteria

An owner view on which index pages are documents is recorded; the chosen rule (or a decision to keep them) is applied and measured on a full build with the count before and after.


## Notes

**2026-11-11T14:44:36Z**

validated 2026-11-11, left open: waits on the owner's view of which index pages are documents; no commit names ct-xj8s since its filing.

**2026-11-11T16:09:08Z**

2026-11-11 BUILT on branch claude/ct-doc-roles-2 (local; tests bc445b69, fix 1a78b492; not pushed, not model-built). Owner decision 2026-11-11: "Per-site list of app pages". Report: .cache/archive-release/investigations/doc-roles-2-20261111/NOTES.md.

Rule: page-signals kind wrapper_url (the ct-aoxp kind, so no SQL change): a site's bare home page on any host (no path, no query), and one entry per committee host for the pages that only index it (calendars and event lists, hearing, markup and news indexes, the Repository's committee list and week and month calendars, a search page). Such a page is a wrapper: no document, its link keys retire with a notice, and it still lists what it links (listed_on). Pages under those indexes stay documents however often linked (event pages, press releases, the 23 parts of CHRG-117hhrg44535).

Predicted on 77673bfb8fcf from capture rows, DuckDB (dr2_16, dr2_17): 192 html documents leave (323,087 -> 322,895); 208 link keys retire, no successor; 267 lookup pairs and 208 addresses go (no address listed elsewhere); 0 meetings, witnesses, measures or recoveries; 446 documents keep one of them as their listing page. Left as documents on purpose: 199 dated floor schedules (docs.house.gov/floor/Default.aspx?date=), owner to say.

Tests (focused, worktree runner): role cases and registry samples fail before (2 failed), pass after (4 passed); nearest five files 31 passed. A full model build must confirm the count before and after; then this closes.

**2026-11-11T16:52:12Z**

2026-11-11 owner: the 199 dated floor schedules (docs.house.gov/floor/Default.aspx?date=) stay documents ("Keep them as documents"); no change to the list.

**2026-11-12T06:30:22Z**

Published in release `ede659a056c04ce0c4f51c70b6848b4eaf1db1a2a2fa8aee04076973e2a1a450` (`nightly/20261112T061147.068599Z`, commit `ea76829fa376980a038cfcc1faa16b9901223cf7`, cause record `model/jobs/release-causes/21fc049940bb-ede659a056c0.json`, notes `docs/releases/2026-11-12-ede659a056c0.md`). Verified on the published Parquet tables against `21fc049940bb`: exact predicted `-192` HTML `wrapper_url` navigation/index documents retired (`323,087 -> 322,965` total documents after `+70` unrelated additions; all 192 removed rows were original HTML pages with 0 meetings, witnesses, measures, or recoveries), all `208` link keys moved to `retired_links.parquet` with removal notices (`0` vanished), `-208` `sources.parquet` addresses and `-267` `urls.parquet` lookup pairs (`266` keys gone + `1` row removed on shared key `b3a3a38dbcd8b8b8`), while keeping the 199 dated floor schedules as documents. Closed.
