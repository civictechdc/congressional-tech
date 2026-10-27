# Review 10 validation (lead)

The Fable reviewer (`fable-review10.md`) read the four docs blind at 41f86b72 and graded them **76/100, C+**. This note re-derives each finding against the docs, the receipts mirror, the 2026-10-15 capture index, the review-9 validation and the owner's decision record.

**Validation score: 84/100.** 13 of 19 findings hold as written. 4 hold only in part (F3, F4, F10, F14). 2 were not checked (F11, F15).

| Finding | Verdict | Evidence |
|---|---|---|
| F1 weekly job's raw loss lands in phase 2 | Holds | PLAN §1 and B14. The rescue only reaches about 3 weeks back through the events API, and nothing schedules a re-run. |
| F2 `legacy_pdf_checks` changes no listing | Holds | DM §7.3: `damaged` needs `intact_basis <> 'unchecked'`. With a legacy record, the 5,978 bodies are `intact` true and a document. Without one, they are unchecked and still a document. Nothing else in the four docs reads `intact_basis`. The record dates from before review 9's "mark unchecked" decision, which made it moot. |
| F3 completion rows | Partly | The sentinel-row cost is as the text describes, and `readings` lists are the precedent. The `name_key` collapse is deliberate per-input dedupe (DM §6.7), and its "lossy" cost was not measured. Phase 2 only. |
| F4 B13 has no stated reason | Partly | The reason exists only in the owner's 2026-10-24 decision 16 and is missing from all four docs: old PDFs get plain, shareable links, and files up to 1.19 GB never pass through the browser. The fix is the reviewer's "+30 words if kept" branch, not deleting B13. |
| F5 older-line rules split between DM §5.2 and §6.1 | Holds | 9 "Older lines" clauses in §5.2. |
| F6 an operational parser failure blocks publish | Holds | DM §6.2 (no row is written) with §7.1 (publish refuses until someone writes `unreadable`). |
| F7 26 registries | Holds | DM §7.1 has 26 rows. The merge is plausible; whether separate versions are needed was not checked. |
| F8 release file list three times | Holds | ARCH §10.1, ARCH §11.1 line 439, DM §8.1. |
| F9 fixture table in the plan | Holds | PLAN §5.3. |
| F10 three 412 policies | Partly | The release HEAD is redundant: the release ID recomputes from content (DM invariant 20). The PDF copier's ETag compare has a reason the docs don't give: old capture writes `.pdf` copies when `store_uncompressed_pdfs` is set, and receipts never record them (0 `bodies/…/<sha>.pdf` keys in 2,289 receipts; the 8,456 `<sha>.pdf` strings are local payload paths). Unrecorded objects may therefore already sit at copier keys. |
| F11 ARCH §11.6 restates DM §9 | Not checked | — |
| F12 ARCH and PLAN disagree on recorded sizes | Holds | ARCH §7.4 says "all 1,036,256", which is wrong. Receipts record sizes for 672,063 bodies; 364,193 (363,990 of them Senate captions) have them only in the old index (`validate-data-review9.md` row 5). The listing baseline then stores the size in raw, so the index dependency ends at B9's first run. Only ARCH needs correcting. |
| F13 the weekly check cannot see bit rot | Holds | ARCH §7.4. |
| F14 three HTML/XML counts | Partly | They are nested populations, not contradictions: 287,765 bodies labeled HTML or XML, of which 214,041 have a 2xx; page-reading candidates add JSON and sniff-chosen bodies (289,179). A re-count on the 10-15 index gives 286,103 ⊃ 212,501, and 286,769 with JSON (`r10v_htmlxml.py`); it differs from the documented figures because the snapshot and selector differ. The real gap is that no doc defines them. |
| F15 the `.gz` logical key in IDs | Not checked | It depends on whether document IDs reach page URLs (the 16-hex ID decision). |
| F16–F19 repetition, plan IDs in specs, ceremony, small items | Hold | F17: DM cites B13 three times, plus B0, E1, A11 and F0. |
