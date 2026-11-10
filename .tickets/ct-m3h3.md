---
id: ct-m3h3
status: open
deps: []
links: []
created: 2026-11-10T19:23:54Z
type: bug
priority: 2
assignee: mikewolfd
---
# Two same-text Ways and Means report PDFs show as separate documents

The recovered-copy rule (ct-u9y4) keeps a recovered file on a document only when the address's own record names it, so two Ways and Means report PDFs whose extracted text is the same now sit on separate rows (live rows 334942 and 335064 in release 619db5f9e08e). They are one document in two files. Decide the join that reunites same-text renditions without re-fusing different documents (candidate: the body-text reading, ct-fk4w), then check the release for other pairs. Shipped knowingly in the 2026-11-10 release; named in its cause record.


## Notes

**2026-11-10T20:38:46Z**

2026-11-10 shipped as an accepted defect in release 77673bfb8fcf. Checked on published release 77673bfb8fcf (2026-11-10T20:27:52Z) against 619db5f9e08e with DuckDB on the published tables. Following link keys from 619db5f9e08e: row 334942 (hr3210rptlegtext.pdf) and row 335064 (hr4954commrptpt1.pdf) each now reach 2 documents. The cause record files the split and shared-key groups under ct-m3h3 as accepted_defect.
