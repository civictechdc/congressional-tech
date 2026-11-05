---
id: ct-zpbl
status: open
deps: []
links: [ct-deh9, ct-xt19, ct-6v77]
created: 2026-11-02T17:45:21Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [versions, phase2, post-release]
---

# Keep parser readings reusable until their meaning changes

Avoid unnecessary rereads while preserving the facts and failure decisions that each parser version produced. Current stamps mix semantic reuse with source bytes and whole-lock changes, while handwritten source lists can miss workspace dependencies. An equivalent SQL edit previously made 25 settled failure decisions ineligible; restoring its bytes repaired that incident.

Use declared reading-parser versions initialized to the current values, with import-closure digests as diagnostic provenance. Preserve the existing advisory-warning policy and deliberate maintainer decision. Plan with `/evolutionary-refactoring` before implementation. Reuse the locked-package analysis from `r4-rca` commit `1f6effdf` after review; adopting that prototype's hashes directly would move existing pins once.

## Current state

Main merge `2d6bd32d` includes reviewed correction `e8c9e0ac` for the maintained direct-writer gap. Fresh capture and local recovery use the configured `pdfinfo` version check only when a PDF needs the external fallback. The final 25-key historical refusal proof remains open.

## Acceptance Criteria

- Preserve current pins, selected logical rows, refusal settlement and pending work at migration without replay. The registry still actively admits an older sniff version through `lock_only`; retaining the current declared value alone does not preserve that selection. Compare both directions on the affected retained partitions before removing the selector or use a separately qualified migration that preserves it.
- Record workspace-module and imported locked-package closure digests. Drift without a declared bump makes CI and `doctor` warn with the existing cheap sample check; the warning permits the run and leaves reuse in place. Record the maintainer's equivalence acknowledgment or deliberate bump when accepting changed code that reuses affected rows. A warning or unchanged sample does not prove equivalence for every input.
- A confirmed change to values, schema, refusal behavior or worker policy moves the relevant version and recomputes only its proven affected population. Preserve external-tool and worker-policy evidence. Remove superseded whole-lock stamping, `lock_only`/`whole` machinery and pinned hashes only once existing selections remain valid. Retain predicate-scoped compatibility and raw primary-key refusal; update `AGENTS.md` and the model-pin workflow.
- Use bounded fixtures for an unrelated locked-package change and a semantic edit in a transitive helper. Show the unrelated change leaves the key, work list and body-open count stable. Show the semantic edit warns but leaves an old row eligible until the intended bump; then show the affected row becomes pending and yields the changed value. Include a changed body outside the ordinary sample to demonstrate the sample's limit. Do not turn this migration check into a corpus replay.

The prior 124,651-row HTML comparison applies to its exact release and rules. Keep `ct-deh9` and `ct-xt19` closed for their delivered work. [Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

## Notes

**2026-11-05T20:18:16Z**

Applied the accepted third-round scope update. The current description records the root cause, delivered work, remaining behavior and bounded checks; historical notes remain unchanged. No implementation or operational action was performed. [Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

**2026-11-05T21:27:18Z**

Reviewed source handoff in `2516ebd1816ad432fe779c8e38e3ea2a6c0dae0c`. The four leaf IDs, separate HTML metadata ID `0fff8151`, combined ID `7b006df1`, and four active compatibility entries are preserved. The raw primary-key preflight and predicate selection remain in use. `doctor` and CI warn on workspace, locked-package, reader, and worker-policy drift and report a fixed fixture result. The warnings leave the declared selection eligible for reuse. The maintainer records equivalence or a deliberate bump. The developer and model-pin instructions now describe that workflow.

With pinned local DocSpec and Poppler 26.06.0, 362 focused checks passed across ten files and 10 more passed across two capture and proof files. After the final sample-timeout fix, 82 overlapping focused checks and the planted `doctor` warning check passed. Bounded fixtures showed that an unrelated lock change left the key, work list, and body-open count stable. A transitive edit changed a body outside the ordinary sample. Its saved row stayed eligible until a deliberate HTML metadata bump, after which the changed body produced the new value. These are partial checks.

The retained native comparison used 278 capture rows and 35 reading rows. The approved HTML merge and the candidate selected the same 30 rows in both directions, including 17 legacy sniff rows, and both left the same 25 bodies pending. The historical `a7a8c404` control accepted all 25 refusals and cleared pending work on that slice with zero raw opens. The comparison establishes selector behavior for those inputs. Refusal equivalence requires the final worker proof. [Source and test handoff](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/versions/STATUS.md) · [Retained comparison](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/versions/retained-selector-r3/summary.json).

Keep this ticket open. After the final source and worker-policy freeze, the release owner will use the existing `prove_bundle` with the pinned runtime and one worker over the exact 25 historical body hashes (9 memory-limit and 16 output-limit refusals), without `--write`. Acceptance requires qualifying one compatibility entry for `7b006df1` and verifying settlement of those exact keys. CI and `doctor` retain the Poppler 26.06.0 prerequisite. Ad hoc receipt calls can bypass it and still stamp the declared sniff ID. Durable evidence of the actual PDF reader for those calls remains with the shared writer.

**2026-11-05T21:42:45Z**

Direct-writer follow-up `e8c9e0acc7cf75c8b1913adceecd8ec44bb107df` is reviewed and locally qualified. The planted mismatch previously let both fresh capture and local recovery record the declared sniff ID and an intact verdict. The fixed callers preserve the raw bytes and record `pdf_reader_unqualified` with no sniff version or intact verdict when the reader is missing or mismatched. The actual pinned reader and trailer-only controls retained the declared ID and verdict. Ten focused checks passed, and independent review confirmed the eight capture and recovery fixture body digests and that the mismatched executable received only the version probe. The final four-control run on the exact commit passed in the pinned local environment. It checked fresh recovery time and metadata, retained-reference lookup without a body read, capture HTML inspection after storage, and selection of a later sniff read when the capture has no accepted facts. That run includes two recovery controls from the earlier ten. The declared IDs and source/runtime pins stay in place. After the final freeze, the release owner still needs to run the exact 25-key refusal proof (9 memory-limit and 16 output-limit cases) with the pinned runtime and one worker, without `--write`, then verify compatibility settlement. [Base reproduction](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/pdf-reader-before.log) · [Guard checks](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/pdf-reader-focused.log) · [Final controls](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/pdf-reader-final-controls.log)
