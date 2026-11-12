---
id: ct-fk4w
status: open
deps: [ct-m704]
links: [ct-h8dr, ct-29n4, ct-yuf0, ct-5q3g]
created: 2026-11-10T10:16:58Z
type: feature
priority: 2
assignee: mikewolfd
tags: [model, filenames, kinds, body-text]
---
# Settle name-kind contradictions and bare Bio labels from the pdf_text reading

The name rule (ct-h8dr) keeps a committee name whenever it contradicts a House slot name, because the model holds no reading of a PDF body. The pdf_text body-text producer already writes text_head (first 2 KB), text_bytes and page_count per PDF body; it is not in the model profile, and its backfill (ct-m704) had read 102,787 of 297,229 published PDF documents on 2026-11-10. Measured on the producer's own text (.cache/archive-release/investigations/name-rule-20261110/nr_40_reading_step.out): 'testimony or disclosure words in the first 2 KB' decides 95 of 132 documents of known kind and is right in 94; 'two pages or fewer and no such words' is a biography in 25 of 26. Over the 1,168 contested slot names read so far the reading supports the committee name for 157 of 172 Bio names and 32 of 43 TTF names, and the official name for 11 of 17 Wstate names. It would also settle the 602 documents with two official names of different kinds, and it says testimony for 621 and disclosure form for 169 of 10,516 documents published as witness-biography, most with no second name.

## Acceptance Criteria

pdf_text is a pinned model input with an empty work list. saved-name-standing.sql keeps a contradicted slot name when the body's reading states its family and drops a committee name the reading contradicts; two official names of different kinds are settled by the reading. A separate decision records whether the reading may correct a kind when the document has one name only. Effect measured against live before it publishes.


## Notes

**2026-11-10T19:23:54Z**

2026-11-10 KNOWN CASE for the reading step: event 101019 (House Ways and Means, 2013-06-20) gains HHRG-113-WM02-Transcript-20130620.pdf in its transcript list in the 2026-11-10 release. The House filed that file under the June 20 event, but its text is the July 10, 2013 hearing 'The Delay of the Employer Mandate'. The archive repeats the House's filing; only a reading of the body's own date and title can catch it. Named in the release's cause record and release note (ct-jcnd item 9 points here).

**2026-11-10T20:38:46Z**

2026-11-10 what release 77673bfb8fcf shows. Checked on published release 77673bfb8fcf (2026-11-10T20:27:52Z) against 619db5f9e08e with DuckDB on the published tables. saved_name_kinds: 3,539 documents whose copies' names state different kinds; committee name leads 2,656; official pairs unsettled 602; other official names lead contradicted 206; slot names leading contradicted 0. One decided body is unmet: saved_name_decisions_unmet 1 (see ct-h8dr). Event 101019's transcript (the July 10, 2013 file the House filed under June 20) shipped as an accepted defect in the cause record (meetings changed transcripts, 112 rows). Nothing here reads PDF text yet.

**2026-11-11T14:41:23Z**

validated 2026-11-11, left open: pdf_text is not a model input yet (model/jobs/publish-model.json binds no body-text table; release 77673bfb8fcf's saved_name_kinds still shows 602 unsettled official pairs per the 2026-11-10 note), and the full body-text run is still in progress. The reading step and the owner's decision on single-name kind correction remain.
