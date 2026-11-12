---
id: ct-jcnd
status: open
deps: []
links: [ct-5q3g, ct-swyw, ct-fk4w, cat2-x47u, ct-lft6, ct-esuu, cat2-8ai9, ct-ywz2, ct-yizl]
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

**2026-11-11T14:42:31Z**

validated 2026-11-11, left open. Done on main (review-fix commits before aef93461): item 1 in part (saved_name_decisions_unmet ships and reports 1), item 2 (f100431e, 1b39ca0c: a details page names a file only by a GovInfo ID, a lost one refuses), item 5 (6a348916: letterless titles caught without the rule's own pattern), item 7 in part (68cde266: 'H.R. ___' is a link word). Remains: item 7's two missed shapes ('H.R.___,', 'H.Res.___') and 'Download...' link text as a title (2,270 in 77673bfb8fcf); items 3, 4, 6 and 8 (model-relation-rows.json still lacks the new steps, see ct-swyw); item 9 waits on ct-fk4w.

**2026-11-12T07:25:00Z**

Closed with all nine review items resolved or explicitly routed:
- (1) `model/sql/saved-name-standing.sql` now grants standing `1` on a `saved-name-decisions.json` body only to copies whose `filename` is listed in `committee_name` (when `decision = 'committee'`) or `official_name` (when `decision = 'official'`), preventing an unreviewed newer copy of the decided class from silently overriding the reviewed copy while `saved_name_decisions_unmet` continues counting bodies whose only remaining copy or `undecided` winner is unread (`test_a_decision_led_by_a_name_the_review_never_read_is_counted`).
- (2) Completed on `main` (`f100431e`, `1b39ca0c`: `LANDING_PAGE_INVARIANTS` + GovInfo ID stem).
- (3) Consolidated DM 7.5 recovery display order and container-ZIP exclusion (`archive_bodies` and `good_archive_containers`) under one owner in `packages/viewer_publication/src/viewer_publication/archive_provenance.py` (`NON_ARCHIVE_RECOVERY_FILTER_SQL`, `RECOVERY_ORDER_SQL`, `saved_recoveries_step`), shared by both `model/sql/provenance-recovered-copy-links.sql` and `model/sql/saved-recoveries.sql`, with planted tests where the newest recovery is a container ZIP (`test_a_link_moves_through_its_shown_copy_or_one_with_the_same_text`).
- (4) Completed on `main` (`7e4b3878`, `ct-5q3g`: all 6 inline title-label regexes consolidated into `label_alone` in `model/registries/title-rules.json` read by `model/sql/titles.sql`, verified against `GENERIC_DOC_TITLE_RE` in `test_generic_doc_title_regex_matches_title_rules_registry`).
- (5) Completed on `main` (`6a348916`: letterless titles caught independently in `GENERIC_TITLE_SQL`).
- (6) Fixed the 3-copy standing rule mismatch in `model/sql/saved-name-standing.sql` (`non_slot_official` running window + standing `3` on contradicted slot/generic official copies) so a committee name does not jump a contradicted non-slot official name merely because a slot copy also stands on the body, while the slot copy still gives way (`test_an_official_name_leads_unless_a_committee_name_contradicts_it`).
- (7) Widened `link_word_bill_placeholder` (`'H.R.___,'`, `'H.Res.___'`, `'S ___.pdf'`), widened `link_word_download` (`'Download ...'` link labels), and added `link_word_filename` (bare filenames used as link text such as `'BILLS-116hr5430rfs.pdf'`) in `model/registries/title-rules.json` + `model/fixtures/registry-samples.json` (`test_a_bill_number_placeholder_is_a_link_word`).
- (8) Synced static registry counts (`saved_name_decisions: 84`, `title_rules: 10`) in `packages/viewer_publication/tests/fixtures/model-relation-rows.json`; full step-log regeneration from remote lake snapshots is tracked on `ct-swyw`.
- (9) House transcript date-vs-kind verification is tracked on `ct-fk4w` (`pdf_text` model step).
