---
id: ct-jcnd
status: open
deps: []
links: []
created: 2026-11-10T14:57:27Z
type: task
priority: 2
assignee: mikewolfd
tags: [model, review]
---
# Next-release model review: follow-ups that do not block the release

From .cache/archive-release/investigations/next-release-review-20261110/model/REVIEW.md (verdict: ship after one named check, no code fix first). (1) The reviewed name registry can be overridden silently: archive_model.py loads only body_sha, decision and evidence, so a new copy of the decided bytes under a new name of the decided class can lead unreviewed while saved_name_decisions_unused stays 0; a typo'd decision acts as undecided. Fix: load the recorded names, add a count saved_name_decisions_unmet, validate at load. (2) A GovInfo details page that is neither a document nor a landing page would vanish uncounted (0 rows today): add a third invariant and anchor the stem to a GovInfo ID shape. (3) The recovered-copy rule restates the recovery display order (provenance-recovered-copy-links.sql against saved-recoveries.sql): one owner, and a test where the newest copy is a ZIP. (4) The title-label regex exists in two versions (4 copies and 2 copies): one title_label kind in page-signals. (5) generic_titles' letterless class comes only from the rule's own pattern; the slot-family list is written three times. (6) Rule-text mismatch in name standing, 0 rows today. (7) Cosmetic: 67 'H.R. ___' placeholder titles; one filename used as a title. (8) model-relation-rows.json lacks the four new steps: regenerate from the all-in build. (9) House transcript names now decide meeting outcomes and are judged by kind, not date: see the note on ct-fk4w.

## Acceptance Criteria

Each item is fixed with a test, or declined with a reason, or split out.


## Notes

**2026-11-10T20:21:23Z**

2026-11-10 item 7, what actually ships in release 77673bfb8fcf (record review): the placeholder-title rule misses two shapes, 'H.R.___,' and 'H.Res.___' (live rows 58914 and 58928 gain them as titles from link text fetched today), and 7 titles start with 'Download'; 12 gained titles are a file name. Recorded as accepted defects on the two changed-title groups of the release's cause record. Fix: widen the placeholder pattern to underscores without a space and trailing punctuation, and drop 'Download…' link text as a title.

**2026-11-10T20:38:46Z**

2026-11-10 what release 77673bfb8fcf shows. Checked on published release 77673bfb8fcf (2026-11-10T20:27:52Z) against 619db5f9e08e with DuckDB on the published tables. Item 7: 18 titles contain an 'H.R. _' style placeholder; 2 are nothing else ('H.R.___,' and 'H.Res.___'); the other 16 are long real titles with a placeholder inside. 'Download...' titles 2,263 -> 2,270. Item 1: saved_name_decisions_unmet shipped and reports 1 on this release: body 3d1434b5... (decision undecided; names BILLS-1145033ih.pdf and HR-5033-ANS.pdf) leads under a third, unread name, SLW_311_xml.pdf (also on ct-h8dr).
