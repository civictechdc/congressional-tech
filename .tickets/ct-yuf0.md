---
id: ct-yuf0
status: in_progress
deps: []
links: [ct-h8dr, ct-fk4w]
created: 2026-11-10T05:18:40Z
type: bug
priority: 1
assignee: mikewolfd
tags: [model, filenames, kinds]
---
# Name rule shows a House repository name that contradicts the committee's own: 54 testimonies now filed as biography or support document

Found 2026-11-10 in the recount of release candidate 619db5f9 (.cache/archive-release/release-20261110/causes-2/document-fields/22-losses.csv). After ct-f7hp returned 1,689 documents to the copy that stored the bytes, 54 of them carry a House-convention name whose kind disagrees with the committee's own file name for the same bytes: 37 read as biography and 17 as support document where the committee name says testimony or another specific kind. Example: 'Testimony - Bryan.pdf' is now 'HHRG-116-HM08-Bio-HentzA-20200311.pdf', a different surname. Median size 230 KB, which looks like testimony. No PDF was read, so which name is right is unverified per document; either the House repository filed the file under the wrong witness and type, or two copies of one upload carry different labels. Same family as the long-term naming rule the owner approved for the next release (convention name, reader fields, then earliest).

## Acceptance Criteria

Each of the 54 is read and classified. The naming rule does not let a repository name override a committee name that states a more specific kind for the same bytes, or the conflict is published as such. A model invariant counts documents whose copies' names imply different kinds.


## Notes

**2026-11-10T13:27:30Z**

2026-11-10 status: the 54 are among the 253 slot names that give way under the name rule on claude/ct-next-release (52 read as statements, 1 amendment, 1 committee action); invariant contradicted_official_saved_names counts them. Still live as published in release 619db5f9e08e (accepted defect). Closes when the next release is out and the 54 are checked on it.
**2026-11-10T10:13:39Z**

Branch claude/ct-name-rule (89f6059a; not pushed, not merged, no model build). Evidence: .cache/archive-release/investigations/name-rule-20261110/README.md, reading sample 05-reading-sample.csv (stratum known54).

Each of the 54 was read (52 from the text layer, 1 from a rendered first page, 1 from the pdf_text producer's OCR). The committee name is right in 54 of 54. The 37 Bio names are all testimony; "Testimony - Bryan.pdf" is William Bryan's testimony under HHRG-116-HM08-Bio-HentzA. The 17 support-document names are 15 testimonies, 1 amendment and 1 committee action.

Rule: an official name contradicted by a committee name of the same bytes (both state a kind, no committee name shares the official family) no longer leads when it is a House meeting-document slot name; the committee name that states a kind leads. Through the pinned engine on the published release's rows, the 54 become: 51 back at the name the release before showed, 3 at a House Wstate name a committee name agrees with; 52 statements, 1 amendment, 1 committee action; none a biography or support document.

Invariant: step saved_name_conflicts lists every document whose leading name's kind another named copy of its bytes does not share (3,531 on these rows), query saved_name_kinds reports them, and model invariant contradicted_official_saved_names (a slot name leading against a committee name) is 0.

Not settled here: 602 documents with two official names of different kinds and no committee name (a Bio and a Wstate name on one file; 22 read: 11 testimony, 5 biography, 5 disclosure form, 1 report), and Bio names with no second name at all. Both need the document read (ct-h8dr, written step).
