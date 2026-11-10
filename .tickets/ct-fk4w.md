---
id: ct-fk4w
status: open
deps: [ct-m704]
links: [ct-h8dr, ct-29n4, ct-yuf0]
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

