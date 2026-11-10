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

