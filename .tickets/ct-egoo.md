---
id: ct-egoo
status: in_progress
deps: []
links: []
created: 2026-11-10T20:37:59Z
type: task
priority: 3
assignee: mikewolfd
tags: [model, record-roles]
---
# GovInfo details pages after the fold: 2 unplaced addresses, the hearing-number title, capture scope

Split from ct-m878 when it closed on release 77673bfb8fcf (2026-11-10). The fold shipped: 0 documents are saved at a govinfo.gov/app/details/ address and 34,824 details addresses sit as unsaved sources on their hearing. Three owner questions from ct-m878's 14:06Z note were never answered: (1) the 2 unplaced pages (unplaced_landing_pages: CHRG-115hhrg24725, CHRG-116hhrg49571, multi-part packages with no package-level file) are listed nowhere now: accept plain removal notices, list the parts at that address, or keep them as documents; (2) whether the details page's title, the only place the hearing number (e.g. 'S. Hrg. 111-774') is published, should fill the hearing's title; (3) capture scope still admits details pages, so each new package adds one more wrapper page to fetch.

## Acceptance Criteria

Each of the three is decided by the owner and either built with a before/after count on a full build or declined with the reason written here.


## Notes

**2026-11-11T14:44:37Z**

validated 2026-11-11, left open: all three are owner questions and none has been answered (no commit or note since the split from ct-m878).

**2026-11-11T16:08:44Z**

2026-11-11 BUILT on branch claude/ct-govinfo-synonyms (404dcf97 tests, 6d2f9b19 fix; local, not pushed, no full build). Owner's choice: list parts, keep number, stop fetching. Investigation: .cache/archive-release/investigations/govinfo-synonyms-20261111/NOTES.md (gs_* scripts, gs-* outputs). Predictions are DuckDB on the live 77673bfb8fcf tables, not a build.

1. List parts. A package page that names no saved file is now an address of each document its granule pages took (landing-pages.sql; the per-page pick moved to landing-page-picks.sql). Because the live ledger carries the two notices as written (empty), retired-links.sql now lists, for a landing page's key, the documents at the page's own address. Predicted: CHRG-115hhrg24725 -> list_rows 93905 (pt1.pdf), 93908 (pt2.pdf); CHRG-116hhrg49571 -> 97784 (add1.pdf), 97786 (err.pdf). +4 unsaved sources rows, +4 urls rows, notices CB0383AF1FD10C1E and 97FB468681B8AC87 list 2 parts each; the other 34,824 page notices are identical under the new rule; unplaced_landing_pages 2 -> 0. Documents and link keys unchanged.

2. Keep number. The number is also in the package's own MODS (<preferredCitation>S. Hrg. 116-439</preferredCitation>, House "Serial No. 115-3"), which capture fetches (govinfo/mods); no model input reads that field yet (neither MODS branch adds it), so this build reads it from the details page title already held (source_annotations.reading_title, all 34,826 pages). Page signal govinfo_details_title keeps only titles that print a number: 19,133 of 34,826 pages; 15,691 print only GovInfo's "House Hearing, 111th Congress" label and fill nothing. The number-bearing title fills a hearing title that is empty or starts "- " (GovInfo's text title with the number slot empty). Predicted: 19,032 of the 34,720 hearing rows change (18,593 "- X" -> "S. Hrg. 118-265 - X", 439 empty filled); 15,677 keep theirs (label-only page); 11 own titles kept. For new packages (no details page) the number needs MODS preferredCitation: follow-up once the MODS hearing-records release lands.

3. Stop fetching. Finding: capture already does not fetch details pages. No capture-scope family ever matched /app/details/ (registry born 2026-10-27) and plan_queue queues only URLs with a family; capture ran 2026-10-30 and 11-08 with no details fetch. The 34,831 url_state rows were captured by the one-off 2026-10-05 CI download as family documents and still read eligible, due weekly. Change: the documents family names ^https?://(www.)?govinfo.gov/app/details/ as an exclusion, so url_state marks those rows excluded (scope_exclusion) and the scheduler counts them done. Predicted: 34,831 url_state rows eligible -> excluded; capture_scope.json changes.

Tests (runner, partial): 404dcf97 failed first (5 failed, 5 passed); after the fix 22 passed (two-build landing test with two parts and the title fill, planted-defect counts, carried-notice ledger test, url_state exclusion with the real registry, scheduler refusal, registry samples). A full build must confirm the counts above and needs cause records for: titles (19,032), sources/urls (+4 each), retired_links address_versions (2), url_state capture_disposition (34,831).

Open for the owner: whether the 15,691 label-only pages ("House Hearing, 111th Congress - X") should also fill "- X" titles (GovInfo's display title, but no number).

**2026-11-11T16:25:45Z**

2026-11-11 tests (runner, partial lines): nearest model files 242 + 18 rerun, test_phase2_model_entities.py 52, release e2e/provenance/evidence/page metadata + test_capture_scheduler.py 134, all passed. Repeat-cost lint: retired_links_export records +932,789 (one more scan of source_rows and details; 2a405428). No full lane or full build run.

**2026-11-11T16:58:12Z**

2026-11-11 owner: hold the title change (titles get one composition rule, designed first; the hearing number becomes its own field shown beside the title). Part 2 is out of this branch: 0c313021 removes the title fill; the work is parked whole on branch claude/ct-egoo-title-fill-parked, commit 1e5b751a (one commit on 0c313021 restoring landing-page-titles.sql, the normalized fill, page signal govinfo_details_title with its samples, the test assertions and DM text; measurements gs-10..12). Parts 1 (list parts) and 3 (stop fetching) stay as built; the title counts in the note above no longer apply to this branch. Owner on label-only titles: numbers only (for the design).
