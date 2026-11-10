---
id: ct-ccsi
status: closed
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 3
assignee: mikewolfd
tags: [model, titles]
---
# New documents take bare numbers and 'Biography' as titles from link text

1,386 documents first titled on 2026-11-10 take their title from link text on 268 newly ingested event pages: 111 are bare numbers, 163 are 'Biography' and one is '.'. No existing title was replaced or emptied. Source: .cache/archive-release/release-20261110/causes/review-DE/REVIEW.md.

## Acceptance Criteria

A link text that is a bare number, punctuation or a generic label is not used as a title when the file name or the page gives a better one; the counts of such titles are measured before and after on a full build.


## Notes

**2026-11-10T13:27:30Z**

2026-11-10 status: fixed on claude/ct-next-release (247bbf6f, 2249baf8, 99e7e0dd). Of the ticket's 275 titles, 103 become 'Biography - <name>' and 172 show their filename; 334 other junk titles change with them. Left: full model build on the stack to measure before/after, review, release. Closes when released.
**2026-11-10T08:49:38Z**

Rule (branch claude/ct-document-roles: tests 50d0e450, fix e8ebafbb; not merged, not built). Two parts, both where the title rule already lives.

1. page-signals gains link word `link_word_no_name`: a text with no letter ("12", "_3", ".", "16-4"), or a numbering word and a number ("no. 3"). Link text, page titles and the `generic_titles` gate all read it. "Exhibit 3", "Amendment No. 3" and titles in any script stay.
2. document-normalized.sql: "biography" joins the labels a witness's name completes ("testimony", "witness statement" and the rest), and a label alone is no longer a title. A named title from any source comes first; else the label takes the document's one witness ("Biography - Mr. Shou Chew"); else the title is empty and the site shows the filename. The label stays only when the document has no filename.

Measured on release 619db5f9e08e (96,434 titled documents of 357,471). Scripts and outputs: `.cache/archive-release/investigations/document-roles-20261110/` (`dr-41-titles.out`, `dr-42-title-effect.out`, `dr-44-title-summary.out`, every changed row in `dr-44-title-changes-all.csv`).

- The committed link-text and page-title SQL through the pinned engine on the release's 1,979,848 links and 333,528 page readings: before the change it gives back the exported 2,086,469 rows exactly; after it, 465 source files lose a link-text title (2 take another link text) and 13 page titles and 14 headings are dropped ("{" and "404"). No source file gains or changes a title otherwise.
- The 275 in this ticket: 103 read "Biography - <name>"; 172 show their filename (60 "Biography" with no witness known, 111 numbers, the one "."). None has a blank filename.
- 334 other titles change, none of them a name: 144 older link texts with no letter (Senate transcript numbers equal to the filename stem such as "19-26-03-26-19", "_3", vote counts); 11 recovered pages titled "{", which take their heading or none; 179 labels alone ("Testimony" 156, "Witness Testimony" 19, "Witness Biography" 3, "written statement" 1). 316 of the 334 showed the same title in the release before last night's.
- Document titles are predicted from the published rows, not built: which file is saved and the witness's name are read from the release (the name rule reproduces all 350 titles the model already composed). A title another format of the document could fill is not modelled.

Alternatives weighed on the same rows:

- Only whole numbers, punctuation and the word "Biography" as link words: fixes the 275 with 19 other changes, but all 163 show a filename (the 103 names are lost) and 136 letterless titles ("_3", "16-4", transcript numbers) stay.
- The chosen rule without "a label alone is no title": 60 "Biography" stay as they are, beside the 179 older labels; 370 titles change. Narrower, but it leaves the defect on 60 of the 163 and treats "Biography" and "Testimony" by the same list with different results only by accident of who has a witness record.
- Keep the label when it is all there is, whatever the filename: that is the release as built.

Limit: document-recovery-normalized.sql holds its own copy of the label list and still titles a recovery-only document with a label alone (none in this release). It is the recovery fix's file and was left alone; the two lists should become one.

Found, not fixed: 2,263 documents are titled "Download <something>" ("Download General" 540, "Download QFR Responses" 464, "Download Responses to Questions for the Record" 325) and 410 by another type word alone ("Transcript" 216, "Hearing Memo" 45, "Hearing Transcript" 42). They name a kind of document, which is more than a number does, so they are outside this rule; whether a kind alone is a title is the same question one size up.

A full model build must confirm: `generic_titles` is 0; no published title is letterless or "no. N" (256 today) or "{" (11); no document with a filename is titled by a label alone (239 today); 103 documents read "Biography - <name>"; and the comparison's changed-title group against 619db5f9e08e holds these 609 documents and no title with a name in it.

**2026-11-10T20:38:25Z**

2026-11-10 SHIPPED, closed. Checked on published release 77673bfb8fcf (2026-11-10T20:27:52Z) against 619db5f9e08e with DuckDB on the published tables, not on notes. Titles in list.parquet, before -> after: with no letter 206 -> 0; 'no. N' 61 -> 0; '{' 11 -> 0; a bare number 58 -> 0; bare 'Biography' 163 -> 0; a label alone (testimony, witness testimony, witness biography, written statement, biography, witness statement, statement) on a document with a filename 342 -> 0; 'Biography - <name>' 0 -> 103; model generic_titles 0. (My patterns are wider than the build note's, hence 206 and 342 rather than 256 and 239.) Left, outside this rule and recorded on ct-jcnd item 7: 2 placeholder-only titles 'H.R.___,' and 'H.Res.___'; 'Download...' titles 2,263 -> 2,270.
