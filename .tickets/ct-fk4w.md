---
id: ct-fk4w
status: in_progress
deps: [ct-m704]
links: [ct-h8dr, ct-29n4, ct-yuf0, ct-5q3g, ct-m704]
created: 2026-11-10T10:16:58Z
type: feature
priority: 2
assignee: mikewolfd
tags: [model, filenames, kinds, body-text]
---
# Resolve remaining PDF-backed filename and document-kind contradictions

## Implementation update — 17 November 2026

Qualified PDF cover evidence is now an exact optional model input feeding the existing cover-kind policy. The canonical publish-model job binds three directly source-reviewed corrections: Saperstein biography -> disclosure; Gudes and Colosimo support files -> disclosure. Two genuine GPO controls retain their previous kinds. The classifier remains unchanged; the two previously missed forms use exact reviewed body decisions, with original classifier output kept as historical evidence.

Portable artifacts and provenance are under `model/jobs/inputs/pdf-cover-evidence-ct-fk4w-20261117.*` and `pdf-cover-review-ct-fk4w-20261117.md`. The artifact SHA is `920fd37ddb3190260f97435e162da4bb3c439ede510fc83d192fb1a3a0a30146`; canonical model-spec SHA is `9eb25725befe6507bb051324bd57a4eec760090be193bfe39363d8886e600268`. Local input pins and focused native policy checks pass. The next full model run will consume this input; no full build/publication is claimed.

Remaining: broader competing-official-name/date conflicts, exposure of unreviewed candidates and before/after full-release comparison. Existing reviewed body decisions do not rename publisher files or invent document associations.

## Audit baseline — 17 November 2026

The latest release reports 63 kind/family changes from newer Tier-1 cover rules. Reuse that work. It does not finish this ticket: `page-facts.sql` currently supplies HTML/XML/JSON readings, `saved-name-standing.sql` still decides from names and reviewed registry entries, and `publish-model.json` binds no pdf_text or docmeta_v6_1 input. An optional docmeta input seam exists but is not enabled there.

Qualified full text now exists for most release bodies. Consume the exact accepted selection and named gaps from ct-m704; remove the obsolete requirement that every PDF work item must complete before any classification can proceed. The historical 602 conflicting official-name pairs and wrong-date hearing example are starting evidence, not current counts.

## Scope and ownership

Reconcile V6 cover/docmeta work and the existing saved-name decision owner before adding classification. Body evidence may settle a contradicted slot or competing official names; unavailable/refused/held text remains unresolved. Keep the separate policy decision for correcting a sole filename's kind explicit. Preserve publisher identity and evidence of a misfiled document rather than inventing a new source association.

## Acceptance Criteria

1. Bind qualified selected PDF text or the maintained derived cover evidence as an exact model input. Report missing/refused/held coverage; no blanket empty-work-list prerequisite.
2. Measure the residual name/kind conflicts on the intended release after existing V6 effects. Resolve source-supported contradictions through one maintained decision path, retaining reasons and actual source/text identity.
3. Record and implement the scoped single-name kind-correction decision separately. Retain ambiguous outcomes rather than treating a filename label or OCR completion as proof.
4. Compare before/after effects on the intended release before publication. Directly review representative raw/body/intermediate/decision results and planted wrong-kind controls; bulk PDF review uses gpt-6.1-terra at medium reasoning. Do not re-extract already-qualified text or duplicate the V6 classifier.

## Audit evidence

17 November manual audit: `<main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md`; PDF sample: the sibling `pdf-manual-review.md`. New v12 files: `<main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/body-text-ssot-20261116/`. These evidence files retain the exact inputs, identities and sampled/unread scope. Historical notes below are dated evidence; the current scope and criteria above supersede their unfinished-work summaries.

## Notes

**2026-11-10T19:23:54Z**

2026-11-10 KNOWN CASE for the reading step: event 101019 (House Ways and Means, 2013-06-20) gains HHRG-113-WM02-Transcript-20130620.pdf in its transcript list in the 2026-11-10 release. The House filed that file under the June 20 event, but its text is the July 10, 2013 hearing 'The Delay of the Employer Mandate'. The archive repeats the House's filing; only a reading of the body's own date and title can catch it. Named in the release's cause record and release note (ct-jcnd item 9 points here).

**2026-11-10T20:38:46Z**

2026-11-10 what release 77673bfb8fcf shows. Checked on published release 77673bfb8fcf (2026-11-10T20:27:52Z) against 619db5f9e08e with DuckDB on the published tables. saved_name_kinds: 3,539 documents whose copies' names state different kinds; committee name leads 2,656; official pairs unsettled 602; other official names lead contradicted 206; slot names leading contradicted 0. One decided body is unmet: saved_name_decisions_unmet 1 (see ct-h8dr). Event 101019's transcript (the July 10, 2013 file the House filed under June 20) shipped as an accepted defect in the cause record (meetings changed transcripts, 112 rows). Nothing here reads PDF text yet.

**2026-11-11T14:41:23Z**

validated 2026-11-11, left open: pdf_text is not a model input yet (model/jobs/publish-model.json binds no body-text table; release 77673bfb8fcf's saved_name_kinds still shows 602 unsettled official pairs per the 2026-11-10 note), and the full body-text run is still in progress. The reading step and the owner's decision on single-name kind correction remain.

**2026-11-13T15:00:26Z**

2026-11-13: The full body-text run (body-text-full-20261110, PID 55948, resumed 2026-11-12 21:32Z after the publish yield) finished 2026-11-13T07:44Z at chunk-0173 with status pending: the work list is exhausted except 411 bodies blocked on missing copy metadata. The 2026-11-13 OCR recovery (codex/ocr-recovery-20261113 @ 56421715, .cache/archive-release/ocr-recovery-20261113, separate recovery catalogs) is retrying all 2,632 leftover bodies; at 14:37Z 2,164 had committed outcomes (1,058 completed, 1,083 parser errors, 23 unreadable) and all 411 missing-pin bodies completed. Still waits on ct-m704 (pdf_text is not a model input yet) and the owner's decision on single-name kind correction.

**2026-11-17T09:17:02Z**

Manual audit credits the latest release's 63 cover-driven kind/family changes and optional docmeta seam. PDF text is still not bound to saved-name standing in the canonical model job. Rewritten around residual conflicts and the separate single-name correction decision, reusing V6 rather than duplicating it. Removed blanket empty-work-list prerequisite in favor of qualified available text plus explicit unavailable/refused coverage. Audit evidence: <main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md.

**2026-11-17T10:28:53Z**

Implemented selected 80/20 scope via subagents. The current implementation update above records completed work, exact evidence and remaining acceptance. Full evidence is under <main checkout>/.cache/archive-release/ticket-fixes-20261117/. Historical notes are preserved.
