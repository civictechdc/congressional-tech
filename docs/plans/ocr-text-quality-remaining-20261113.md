# Remaining OCR and text-quality work — 13 November 2026

The GPO cleanup and optional diagnostic evidence are merged in [PR #151](https://github.com/civictechdc/congressional-tech/pull/151), commit `2cef1dbde71f842d527b6a9cfb8893ff8c16dc25`. All ten CI checks passed. Bounded integration covered 14 archived PDFs / 281 pages through the real CT consumer; independent source review approved that scope. Corrected historical text has not yet been published.

## Remaining work and ownership

| Work | Ticket | State and completion boundary |
| --- | --- | --- |
| Shared accepted-reading selection | [ct-55qo](../../.tickets/ct-55qo.md) | In progress; qualified baseline and per-body exceptions across planning, export and refusal counts. |
| Durable page checkpoints | [ct-aitp](../../.tickets/ct-aitp.md) | In progress; spicy-docs selected pages and streamed observations, then existing document cleanup. |
| Reconcile resource failures and paused recovery | [ct-a73a](../../.tickets/ct-a73a.md) | Paused after batch 205; fix request memory attribution and reconcile original identities. |
| Publish corrected historical GPO readings | [ct-kfsd](../../.tickets/ct-kfsd.md) | New; qualify affected scope, selective reread and current selection. Code integration is already complete. |
| Incomplete native layers and vector text | [ct-hz8y](../../.tickets/ct-hz8y.md) | New; source-qualified page coverage and OCR routing. |
| Native geometry failures | [ct-yy07](../../.tickets/ct-yy07.md) | New; classify failures and qualify narrow OCR fallback. |
| Page-local recognizer crashes | [ct-t4p3](../../.tickets/ct-t4p3.md) | Qualify alternate settings on the exact failing page; shared checkpoints belong to ct-aitp. |
| Hybrid OCR and transcription quality | [ct-n3ik](../../.tickets/ct-n3ik.md) | Text census ranks candidates; source features and independent classification are still needed. |
| HTML/XML text normalization | [ct-cbkz](../../.tickets/ct-cbkz.md), upstream `ss-mkxe` | Credit upstream commits; finish contextual HTML gaps, compose one wheel and measure CPU-only rereads. |
| HTML encoding, XML subsets and event limits | [ct-f6hr](../../.tickets/ct-f6hr.md) | New; separate compatibility acceptance from normalization. |
| Error/empty/landing roles and capture history | [ct-en4n](../../.tickets/ct-en4n.md) | New; qualify detection and identify genuinely unresolved sources using retained evidence. |
| Publisher refetch | [ct-z4w5](../../.tickets/ct-z4w5.md) | Deferred by the user; depends on detection/history qualification and a later decision to resume. |

## Sequence and limits

1. Keep OCR paused. The frozen recovery and follow-up OCR jobs remain stopped; the paused-resume guard stays in force. Code, tickets, retained-data analysis and native/scripted fixtures can progress.
2. Implement ct-55qo and ct-aitp once. Prove mixed accepted versions and interrupted page reuse before changing production selection. A completed current attempt awaiting qualification must not be repeatedly extracted.
3. Compose one bounded spicy-docs candidate for ct-cbkz/ss-mkxe and ct-f6hr, retaining the merged GPO repair. The retained non-OCR inventory contains 310,964 HTML/XML bodies and about 11.92 GB of existing text; measure representative and largest-input CPU cases before estimating or running bulk parsing. WARC requires separate payload/reachability qualification.
4. Diagnose and repair only identified bad PDF pages/bodies. Reuse qualified pre-cleanup observations where identity permits; do not re-OCR all PDFs. The 18,777-body triage set contains candidates, not that many confirmed failures. Its 146 reviewed body/page actions include controls and unresolved candidates. Do not repeat the text census or interpret it as source completeness.
5. Use maintained region, Tesseract or LLM/VLM capabilities for justified complex cases with exact settings and independent omission/value/order checks. The five conditional LLM candidate bodies have no qualified LLM results.
6. Publish qualified selections through existing gates after cohort acceptance. Retain prior readings/refusals; defer compaction. Keep publisher refetch deferred under ct-z4w5.

Operational completion and source completeness remain separate. Preserve valid empty results, old refusals and recovery evidence. Carry forward only readings proved unaffected, and declare semantic changes rather than restamping old rows. The current recovery does not silently adopt the new cleanup policy.

## Evidence and follow-on consumers

The durable local evidence root is `<main checkout>/.cache/archive-release/ocr-recovery-20261113/`. `coordination/text-quality-audit-20261113/repair-plan.md` contains the mechanism-by-mechanism design and source-review references; `repairs/ct-gpo-consumer-20261113/` contains consumer readback. The corpus/source review lives under `.cache/archive-release/investigations/text-quantity-review-20261113/`.

The finalized pause receipt at **18:32:53 UTC on 13 November** records **2,422/2,632** committed outcomes: **1,316 completed, 1,083 errors and 23 unreadable**, leaving **210** targets. Batch 206 has an interruption receipt and no committed result. `PAUSED.md`, `pause-state.json` and `pause-request.json` preserve the stop; no automatic follow-up started.

The independent audit is retained under `coordination/greybeard-root-cause-20261113/review.md`; `inventory/README.md` names the frozen CPU and targeted-page cohorts. The audit's earlier instruction to let OCR finish is superseded by the user's explicit pause. Ticket rewrites distinguish shared selection and lost page work from native coverage, geometry refusal before routing, markup adoption/compatibility, worker-lifetime RSS attribution and source-role/history gaps.

Closed `ct-chc4` covers the earlier script/JSON-LD/CSS leakage fix, not the newly identified markup and response-role gaps. Existing `ct-fk4w` owns downstream document-name/kind decisions using PDF text; `ct-m704` owns search integration. These consumer tickets remain separate from extraction-quality acceptance.
