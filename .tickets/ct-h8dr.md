---
id: ct-h8dr
status: in_progress
deps: []
links: [ct-yuf0, ct-f7hp]
created: 2026-11-10T05:38:12Z
type: feature
priority: 2
assignee: mikewolfd
tags: [model, filenames, owner-decision]
---
# File names: a document takes its official House name whenever a copy has one, unless that name contradicts the committee's

Owner decision 2026-11-10 (questions dialog): adopt the broader name rule in the next release. Measured by simulation for ct-f7hp ('convention name, reader fields, then earliest'): 27,633 documents renamed, none losing information; 20,298 documents currently show a plain name beside a convention-named copy. Evidence: .cache/archive-release/release-20261110/fixes/saved-name/ (fs-05-effect.out, fs-10-final.out). It must NOT ship as simulated: the published release 619db5f9e08e showed that the House repository's slot names are sometimes wrong. 54 documents whose committee name says testimony now carry a House 'Bio' (37) or support-document (17) name; 13 of 13 read are testimony, one under another witness's surname (ct-yuf0); the live release before it already had 63 such contradictions by name and 1,688 'biographies' over 400 KB. So the rule needs a way to settle a House name against a committee name that states a different kind: by kind agreement, by the reading of the document, or by keeping the committee's name when they disagree.

## Acceptance Criteria

The rule is built and measured on a full model build, not simulated: renames against live with gains, losses and neutral counted; no document whose committee name and House name state different kinds takes the House name without a reading of the document that supports it; the 54 ct-yuf0 documents read as testimony; the rename list is reviewed like the 2026-11-10 one before it publishes.


## Notes

**2026-11-10T13:16:36Z**

Owner decision 2026-11-10 on the 343 non-slot official names against a committee kind: 'Review them manually'. Each is read and decided per document; until then they stay as published (the built behaviour on claude/ct-name-rule).

**2026-11-10T13:27:30Z**

2026-11-10 status: the name rule is built on claude/ct-next-release (0f427b29..c03c43da): 18,033 renames measured, 17,778 gain an official name, 253 contradicted slot names give way. Lanes green on a43f83d1. A reader is going through the 343 clashes one by one (.cache/archive-release/investigations/name-clash-review-20261110/decisions.csv). Left: full model build on the stack (none run yet), the 343 sheet checked by the owner, review, release. Follow-ups filed on the branch: ct-fk4w (settle a contradiction by reading the document), ct-29n4 (Truth in Testimony filename reader defect).

**2026-11-10T13:36:28Z**

2026-11-10 the 343 clashes were read one by one (opus reader; .cache/archive-release/investigations/name-clash-review-20261110/decisions.csv and README.md; list reproduced exactly, 85 official / 258 committee shown today). Decisions: both 140 (official name better 132, committee better 8), committee 105, official 72, undecided 25, neither 1. 237 rest on read text, 81 on other evidence (32 GovInfo's own hearing PDFs, 42 one-page notices by size, 7 same wording), 25 on names only and left undecided. Applying all would change 153 shown names: 137 to the official name (67 printed hearings, 57 Ways and Means vote tallies, 13 others) and 16 Rules Committee documents to the committee name. Zero-exception patterns: GovInfo printed hearing against 'transcript'/'nomination' = both, official better (132, 100 read); Ways and Means vote tally named after the amendment = official (57 of 57 read); generic House cover-page name gives way to 'notice' (21 read; already what is shown). Side effect to fix first: the 16 would take the link text 'PDF' as their title. Reader slips found ('ANS' read as print, 'Vote-Tally' as amendment, Act titles with 'Amendments' as amendment) belong with ct-29n4. The sheet was sent to the owner to check; nothing is applied yet.
**2026-11-10T10:13:39Z**

Branch claude/ct-name-rule (89f6059a; not pushed, not merged, no model build). Evidence and scripts: .cache/archive-release/investigations/name-rule-20261110/README.md.

Measured on the published release 619db5f9e08e. 35,784 documents hold two or more names on copies of the saved bytes; 24,991 hold an official and a committee name. Kinds agree on 15,650, the committee name is silent on 6,494, and they differ on 2,847: support document against a specific committee kind 1,995, Bio against statement or disclosure 371, TTF against statement 100, Wstate against another kind 34, other official names 341. Dates differ on 438 and committee codes on 37 beyond short forms. 686 documents hold two official names of different kinds.

Read: 332 documents (all 54 known cases, 17 strata, fixed seed; 9 scans not read). Bio against a committee "testimony" name: the committee is right in 66 of 67. TTF against another kind: 14 of 17. Support document against a committee kind: the committee name is right and says more in 55 of 58. Wstate against another kind: both right in 6 of 10. Other official names (GovInfo hearing against "transcript", vote record against "amendment"): official right or equivalent in 11 of 15. Kinds agree: both right in 67 of 67. A surname missing from the committee name is no signal (official witness right in 25 of 25). File size is no signal (over 400 KB: 23% hits, 49% false alarms); a committee name stating another kind is (89 of 89 wrong witness-slot names, 11 false alarms in 75).

Rule built (model/sql/saved-name-standing.sql, one more order key in saved-files.sql). Among the saved body's named, addressed copies: an official name leads unless it is contradicted (it states a kind, a committee name of the same bytes states a kind, no committee name shares a family with it). A contradicted House slot name (biography, disclosure, statement, supporting-material) gives way to a committee name that states a kind. Then the shipped order (stored the bytes, newest). The saved body cannot move. Step saved_name_conflicts recomputes every document whose leading name's kind another name does not share; invariant contradicted_official_saved_names = 0; query saved_name_kinds.

Effect, committed SQL through the pinned engine on the release's own rows (main's SQL on the same rows gives the published name for 351,302 of 351,302): 18,033 documents renamed, no saved body moves. 17,778 take an official name where a plain one showed. 253 slot names give way (248 to the committee name, 5 to the official name a committee name agrees with). 2 committee names that state a kind replace one that states less. No other loss of a reader field. Of the 20,298 plain names beside an official copy, 2,520 stay because the names state different kinds. The 61 losses ct-f7hp accepted: 56 as published, 5 take a House name. Kind changes on 16,343 documents, family on 5,811, facts on 18,001; 44 of those values are predictions (the published value was a fill or an override).

Title side effect, fixed in document-rendition-titles.sql, predicted not built: an official copy is often listed on no page, so 613 renamed documents would lose the committee link text that titles them. The last fallback title is now the link text of another copy of the same bytes: 0 lose a title, 278 renamed and 448 other documents gain or change one, none generic by the gate's vocabulary.

Alternatives on the same data (renamed / gain / give way / other loss / the 54 as testimony / contradicted official names left showing): official always 20,298 / 20,298 / 0 / 0 / 0 / 2,925; as simulated last night (official, fields, earliest) 26,627 plus 93,853 address moves / 20,298 / 18 / 116 / 0 / 2,925; strict (any contradicted official name gives way) 18,120 / 17,778 / 338 / 1 / 52 / 72; official only when not contradicted, nothing gives way 17,783 / 17,778 / 5 / 0 / 3 / 405; built 18,033 / 17,778 / 253 / 0 / 52 / 157.

OWNER DECISION, not built: 343 documents whose official name is not a House slot and whose committee name states another kind (GovInfo hearing against "transcript" or "nomination" 130, vote record against amendment 68, committee document against notice 67, bill names about 60). 85 show the official name today and 258 a committee name; the built rule leaves all 343 as published. Option A, official leads: 258 more official names, about 67 notices become a generic committee document. Option B, committee leads: 85 official names give way and 63 GovInfo hearings take a committee "transcript" name and its link text as title. Option C, as built: no change.

Written step, not built: settle a contradiction by reading the document. The model holds no PDF reading (page_facts is html, xml and json). The existing pdf_text body-text producer already writes text_head, text_bytes and page_count per PDF body; it is not in the model profile and its backfill (ct-m704) has read 102,787 of 297,229 published PDF documents. On the producer's own text, "testimony or disclosure words in the first 2 KB" decides 95 of 132 sample documents and is right in 94. Over the 1,168 contested slot names it has read: Bio 172 read, committee name supported 157, official 0; TTF 43 read, committee 32, official 7; Wstate 17 read, official 11. The same reading says testimony for 621 and disclosure form for 169 of 10,516 published "witness-biography" documents, most with no committee name: that needs a kind rule, not a name rule.

A full model build must confirm: the 18,033 renames and their split on its own diff against live; saved_name_kinds near 3,531 documents, 2,770 led by a committee name, 602 unsettled official pairs, 85 non-slot; contradicted_official_saved_names = 0 and generic_titles = 0; no renamed document loses its title; the 44 predicted values; time and memory of saved_name_standing on the full document_members.
