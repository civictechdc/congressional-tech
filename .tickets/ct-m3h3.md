---
id: ct-m3h3
status: closed
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

**2026-11-11T14:42:31Z**

validated 2026-11-11, left open: still an accepted defect in 77673bfb8fcf (rows 334942 and 335064 each reachable as 2 documents, per the 2026-11-10 note). No join for same-text renditions exists yet; the candidate is the body-text reading (ct-fk4w), which is not a model input.

**2026-11-13T05:41:52Z**

2026-11-13 release acceptance complete. Published archive 55c14dcda87ae954583bf518050b3bd45db6aed49c88c53413260c1d092ef105 reunites the two exact reviewed Ways and Means PDF pairs. Both original URL/body key pairs, both archived renditions per report, legacy lookups and recovery rows survive. The PDFs differ only by one trailing line feed after EOF; this is a bounded exception, not a broad text-similarity merge. All seven unrelated controls remain unchanged.

The full model used the frozen 35,897 receipts; all six invariant suites passed. The release comparison found no vanished/dangling keys or changed file answers. Twelve exact reviewed groups account for the two merges, two source URLs and DataFusion 55 metadata changes. The normal controller reused its completed model and passed the site contract, public canary and conditional pointer update. Independent public readback verified the manifest and target tables; the actual MCP reader fetched all 34 files, resolved both old keys per report, confirmed 31/109 pages, round-tripped citations and rejected a wrong body hash. See docs/releases/2026-11-13-55c14dcda87a.md and durable evidence .cache/archive-release/implementation/ct-release-20261112T2215/ct-m3h3/RELEASE-ACCEPTANCE.md.
