# Remaining OCR and text-quality work — 13 November 2026

The GPO cleanup and optional diagnostic evidence are merged in [PR #151](https://github.com/civictechdc/congressional-tech/pull/151), commit `2cef1dbde71f842d527b6a9cfb8893ff8c16dc25`. All ten CI checks passed. Bounded integration covered 14 archived PDFs / 281 pages through the real CT consumer; independent source review approved that scope. Corrected historical text has not yet been published.

## Remaining work and ownership

| Work | Ticket | State and completion boundary |
| --- | --- | --- |
| Finish frozen recovery and resource retries | [ct-a73a](../../.tickets/ct-a73a.md) | Running; finish integrity checks, reconcile exact original bodies, then publish outcomes. |
| Publish corrected historical GPO readings | [ct-kfsd](../../.tickets/ct-kfsd.md) | New; qualify affected scope, selective reread and current selection. Code integration is already complete. |
| Incomplete native layers and vector text | [ct-hz8y](../../.tickets/ct-hz8y.md) | New; source-qualified page coverage and OCR routing. |
| Native geometry failures | [ct-yy07](../../.tickets/ct-yy07.md) | New; classify failures and qualify narrow OCR fallback. |
| Page-local recognizer crashes | [ct-t4p3](../../.tickets/ct-t4p3.md) | New; preserve valid checkpoints and measure alternate settings' accuracy. |
| Hybrid OCR and transcription quality | [ct-n3ik](../../.tickets/ct-n3ik.md) | Existing; reuse feature census, measure typeset/scanned split and cost before wider adoption. |
| HTML/XML text normalization | [ct-cbkz](../../.tickets/ct-cbkz.md), upstream `ss-mkxe` | Existing; verify shared-reader work, integrate and qualify CPU-only rereads. |
| HTML encoding, XML subsets and event limits | [ct-f6hr](../../.tickets/ct-f6hr.md) | New; separate compatibility acceptance from normalization. |
| Error/empty/landing roles and capture history | [ct-en4n](../../.tickets/ct-en4n.md) | New; qualify detection and identify genuinely unresolved sources using retained evidence. |
| Publisher refetch | [ct-z4w5](../../.tickets/ct-z4w5.md) | Deferred by the user; depends on detection/history qualification and a later decision to resume. |

## Sequence and limits

1. Let the frozen recovery finish under its existing source pins. Verify final tables, retry resource failures serially and reconcile every target before publication. Its 2,632 targets do not cover quality defects in previously completed readings.
2. Qualify historical GPO exposure and publish corrected affected readings under the merged versions. Preserve the independent review's bounds: exact agreement on 281 pages does not mean 281 pages were newly read visually. Ambiguous printing-operator labels remain an explicit preservation tradeoff.
3. Native coverage, geometry, recognizer fallback, markup and response-role work can progress independently with their named source cases and controls. Coordinate shared-reader changes before choosing one integrated version. Do not rerun the completed corpus feature census.
4. Once detection/history work is qualified, retain a deduplicated refetch proposal. Do not initiate publisher retrieval while the user's deferral remains in effect.

Operational completion and source completeness remain separate. Preserve valid empty results, old refusals and recovery evidence. Carry forward only readings proved unaffected, and declare semantic changes rather than restamping old rows. The current recovery does not silently adopt the new cleanup policy.

## Evidence and follow-on consumers

The durable local evidence root is `<main checkout>/.cache/archive-release/ocr-recovery-20261113/`. `coordination/text-quality-audit-20261113/repair-plan.md` contains the mechanism-by-mechanism design and source-review references; `repairs/ct-gpo-consumer-20261113/` contains consumer readback. The corpus/source review lives under `.cache/archive-release/investigations/text-quantity-review-20261113/`.

At the 17:38Z recovery snapshot, 2,356 of 2,632 targets had committed outcomes: 1,250 completed, 1,083 parser errors and 23 unreadable. Batch 198 was active; 276 targets remained. This is a dated snapshot, not a claim that all remaining bodies will be recoverable. `resume-state.json`, `summarize_progress.py` and final summary/integrity receipts are the current-state authorities.

Closed `ct-chc4` covers the earlier script/JSON-LD/CSS leakage fix, not the newly identified markup and response-role gaps. Existing `ct-fk4w` owns downstream document-name/kind decisions using PDF text; `ct-m704` owns search integration. These consumer tickets remain separate from extraction-quality acceptance.
