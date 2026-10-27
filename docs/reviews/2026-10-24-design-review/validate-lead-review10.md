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

## Owner decisions (2026-10-26) and what changed

- **Doc fixes, all.** Fixed or folded in place: F4, F5, F8, F9 (fixtures now in `docs/plans/fixtures-20261026.md`), F10 (the release HEAD dropped; the copier's check kept, with its reason), F11, F12, F13, F14 (the populations defined once; repeated counts dropped from schema notes; counts that justify a rule stay), F16, F17, F18 (tables of contents gone, and the boilerplate status sections of the two specs and the plan; BIND keeps its status section, which holds its path conventions; the W3C labels and key words stay) and F19. Two F19 items were left on purpose: the chamber spelling map stays in DM §3 because it covers several inputs, and DM §7.8's PK is the tested uniqueness §3 defines.
- **Weekly job into raw (F1).** New plan B15, phase 1, first: each run writes its records to raw as an import run, and the rescued batch is imported once.
- **Legacy PDF checks dropped (F2).** Unchecked: 32,087.
- **Simplifications (F3, F6, F7).** Parser tables keep one row per input with list columns; a parse that crashes is retried once, then recorded as `error`; 26 registries become 17.

## Second pass (`fable-rereview10.md`): 84/100, B

The lead checked N1–N8 against the text, and all hold. N1 is a determinism argument: crash and time bounds depend on the run. Fixed in place:
- **N1, by owner decision:** a second crash now writes a producer `unreadable` decision in provenance rather than an `error` row, so a rebuild from raw skips the same inputs. This replaces F6's `error_type = 'crash'`.
- **N2, N4, N5 (both), N6, N7.**

N3 (the weekly runs as an "import run") and N8 (B15's receipts before B0's patch) wait for the weekly-job patch, so they match its real line shape.
