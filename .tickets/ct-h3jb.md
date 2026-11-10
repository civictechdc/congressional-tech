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

Release candidate a70ebc3d1466 (built at 8c3a3cae) fused documents that are separate on the live site. Data model 7.5 rule (a) reads every table row or list item on a publisher page as one document in several formats, checked only by 'one body per format'. A row that holds a PDF and a link to some web page passes that check, so the page became the PDF's HTML version; where one listing page sits beside a PDF on seven event pages, the seven PDFs chained into one document and six could no longer be opened.

Measured on the candidate's exported groups (36,545 valid rendition groups, whole corpus): 28 valid publisher groups hold files whose names differ, and all 28 are wrong joins: 27 pair a PDF with a web page (7 Financial Services SD002 PDFs through one listing page, 4 State Department reports through one page, 16 one-to-one press-release or event pages), and 1 pairs a witness's testimony PDF with an unrelated PowerPoint (aging.senate.gov, live today). Every other valid group (35,793 publisher, 724 same-stem) holds files of one stem.

Rule chosen: a publisher item is a rendition group only when its remaining files share one filename stem, as well as one body per format. Being listed together is not enough; renditions of one document carry one name.

Scripts and outputs: .cache/archive-release/release-20261110/fixes/join-rule/ (fj-*).

## Design

Weighed on the same data (fj-05-alternatives.out). (a) HTML-only stem rule: removes 27 of 28, leaves the PowerPoint join, and is a special case of the rule chosen. (b) 'a body in several groups is a rendition of none': removes 11 of 28 and splits 1,738 correct pairs (bills listed on two weekly pages). (b refined) and (c) 'reject a closure holding two bodies of one format': remove 11 of 28, leave the 16 one-to-one page joins and the PowerPoint, and split 2 correct documents that hold two byte-variants of one named bill PDF. Putting the stem in the group key instead (pairs by name inside a mixed item) also removes all 28, but newly joins 1,232 GovInfo multi-part pairs (hearing plus errata or addenda, 341 packages) and with them fuses one errata PDF into another hearing, because GPO shipped the same HTML bytes under both names (CHRG-114hhrg93279-err.htm = CHRG-114hhrg94738.htm). That is a wider change with its own hazard; it is left as a follow-up, not folded into this fix.

Known limit of the rule chosen: an item whose one body is known under two names no longer joins its other format (no such valid group exists today).

## Acceptance Criteria

A fixture with one listing page beside each of several PDFs yields separate documents; an HTML and PDF of one name still join; files of one body still merge. On the rebuilt candidate: the six Financial Services link keys (28f7a541731b530b, f209387c5948760f, e0560d54500bf13e, 45027a7365cdc1f1, 7b63de014d2cd6a2, d5f411b954a0c3bf) each answer their own file; no valid rendition group holds two stems; the 19 documents listed in fj-10-effect.out become 47; rows 150775 and 153462 stay merged.

