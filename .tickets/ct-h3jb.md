---
id: ct-h3jb
status: in_progress
deps: []
links: []
created: 2026-11-10T03:39:42Z
type: bug
priority: 1
assignee: mikewolfd
tags: [model, archive, renditions, release-20261110]
---
# A publisher item joins files as one document only when they share a filename stem

Release candidate a70ebc3d1466 (built at 8c3a3cae) fused documents that are separate on the live site. Data model 7.5 rule (a) reads every table row or list item on a publisher page as one document in several formats, checked only by "one body per format". A row that holds a PDF and a link to some web page passes that check, so the page became the PDF's HTML version; where one listing page sits beside a PDF on seven event pages, the seven PDFs chained into one document and six could no longer be opened.

Measured on the candidate's exported groups (36,545 valid rendition groups, whole corpus): 28 valid publisher groups hold files whose names differ, and all 28 are wrong joins. 27 pair a PDF with a web page (7 Financial Services SD002 PDFs through one listing page, 4 State Department reports through one page, 16 one-to-one press-release or event pages), and 1 pairs a witness's testimony PDF with an unrelated PowerPoint (aging.senate.gov, live today). Every other valid group (35,793 publisher, 724 same-stem) holds files of one stem, by the model's names and by their addresses.

Rule chosen: files a publisher lists in one item are one document's formats only if they also share a filename stem. The stem joins the publisher group key; "one body per format" is still judged over the whole item, so the change only removes joins.

Scripts and outputs: `.cache/archive-release/release-20261110/fixes/join-rule/` (`fj-*`).

## Design

Weighed on the same data (`fj-05-alternatives.out`):

- HTML-only stem rule (the reviewer's): removes 27 of 28, leaves the PowerPoint join, and is a special case of the rule chosen.
- "A body in several groups is a rendition of none": removes 11 of 28 and splits 1,738 correct pairs (bills listed on two weekly pages).
- "A body paired with two bodies of one format is a rendition of none", and "reject a closure of groups that holds two bodies of one format": each removes 11 of 28, leaves the 16 one-to-one page joins and the PowerPoint, and splits 2 correct documents that hold two byte-variants of one named bill PDF.
- Stem in the key with no item check: also removes all 28, and newly joins 1,232 GovInfo pairs inside multi-part packages (hearing plus errata or addenda, 341 packages). One of those fuses an errata PDF into another hearing, because GPO shipped the same HTML bytes under both names (CHRG-114hhrg93279-err.htm equals CHRG-114hhrg94738.htm). Not taken here: it adds joins, and one of them is the fault this ticket fixes.

Follow-up, not filed: join the 1,232 named pairs by dropping the item check, once a body that two differently named groups claim is kept out of both.

Not changed: an item whose files have no stem at all (432 publisher memberships, none in a valid group) is judged as before.

Not changed either: an HTML body at a file-shaped address (`/files/`, `/download/`, `/uploadedfiles/` and the other routes in `model/registries/file-shapes.json`) is not a real file (`record-roles.sql`), so an HTML rendition served from such a route cannot join its PDF whatever the join rule says. On the candidate no valid group, before or after the fix, holds an HTML member at a file-shaped address, and none of the 236 HTML documents that are not real for that reason alone shares a stem and a publisher item with a real file of another format; 16 share a directory and stem with one, all an HTML response at the PDF's own address (`fj-13-file-shaped-html.out`, `fj-14-file-shaped-samedir.out`).

## Acceptance Criteria

A fixture with one listing page beside each of several PDFs yields separate documents; an HTML and PDF of one name still join; files of one body still merge. On the rebuilt candidate: the six Financial Services link keys (28f7a541731b530b, f209387c5948760f, e0560d54500bf13e, 45027a7365cdc1f1, 7b63de014d2cd6a2, d5f411b954a0c3bf) each answer their own file; no valid rendition group holds two stems; the 19 documents listed in `fj-10-effect.out` become 47; rows 150775 and 153462 stay merged.

## Notes

**2026-11-10**

Done on branch claude/ct-join-rule (local commits, not pushed): tests 7a992762, fix 18f3b854.

Correction: 63339a55 rewrote `test_a_listing_label_outranks_another_formats_page_title` and was committed without being run; the passing run reported before it predates it. A full lane on 7b888308 failed on that test. Cause: the rewrite put the HTML under `/files/`, where an HTML body is not a real file, so it was neither an alternate nor a row and the join rule never saw it (`fj-37-debug.out`). The HTML now sits at a page address with the same stem and joins (`fj-37-debug-hearings-text.out`); the rule did not change.

- Before the fix the five new cases fail (four group cases, one end-to-end release case); after it all pass (`fj-30-test-before.out`, `fj-31-test-after.out`).
- The committed SQL, before and after, run through the pinned engine on the candidate's real rows (`fj-40-native.out`): the old SQL gives back the exported 619,919 members and 73,091 valid rows exactly; the new SQL gives 73,035 valid rows in 36,517 groups, adds none, and drops 56 rows in exactly the 28 groups above.
- Predicted documents (`fj-10-effect.out`): 19 candidate documents become 47. Against live, 17 of them return to the live shape; live row 28415 (four State Department reports and a page) becomes 5 documents and live row 305452 (testimony plus PowerPoint) becomes 2; four pages captured since live become their own rows.

Still to confirm on a full model build: the acceptance list above, and that titles, dates and meeting links of the 47 documents match their live rows where one exists. No model build was run.
