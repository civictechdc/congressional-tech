# Remaining OCR and text-quality work — 13 November 2026

The GPO cleanup and optional diagnostic evidence are merged in [PR #151](https://github.com/civictechdc/congressional-tech/pull/151), commit `2cef1dbde71f842d527b6a9cfb8893ff8c16dc25`. All ten CI checks passed. Bounded integration covered 14 archived PDFs / 281 pages through the real CT consumer; independent source review approved that scope. Corrected historical text has not yet been published.

## Remaining work and ownership

| Work | Ticket | State and completion boundary |
| --- | --- | --- |
| Shared accepted-reading selection | [ct-55qo](../../.tickets/ct-55qo.md) | Closed after actual 14-body planner/export qualification: eight corrected readings and six unchanged actual keys. Historical publication remains ct-kfsd. |
| Durable page checkpoints | [ct-aitp](../../.tickets/ct-aitp.md) | Closed after composed checks and independent raw/checkpoint/output review. Exact-page replacement survives two late-page exits and reuses matching pages. Real recognition stays paused. |
| Reconcile resource failures and paused recovery | [ct-a73a](../../.tickets/ct-a73a.md) | Request memory attribution fixed; 31 retained outcomes reconciled. Qualify candidate text, resolve three outstanding cases and eventually resume only the remaining 210 targets. |
| Publish corrected historical GPO readings | [ct-kfsd](../../.tickets/ct-kfsd.md) | New; qualify affected scope, selective reread and current selection. Code integration is already complete. |
| Incomplete native layers and vector text | [ct-hz8y](../../.tickets/ct-hz8y.md) | New; source-qualified page coverage and OCR routing. |
| Native geometry failures | [ct-yy07](../../.tickets/ct-yy07.md) | Typed reasons and opt-in fallback implemented; old persisted failure classification preserved. Remaining geometry cohort and accurate replacement text still require qualification. |
| Page-local recognizer crashes | [ct-t4p3](../../.tickets/ct-t4p3.md) | Qualify alternate settings on the exact failing page; shared checkpoints belong to ct-aitp. |
| Hybrid OCR and transcription quality | [ct-n3ik](../../.tickets/ct-n3ik.md) | Exact-page routing implemented. The [corpus assessment plan](corpus-text-assessment-20261113.md) reuses retained page features and Keeplist evaluation findings. A bounded offline assessor is in progress; independent held-out calibration remains. Scores rank review; they do not qualify text. |
| HTML/XML text normalization | [ct-cbkz](../../.tickets/ct-cbkz.md), upstream `ss-mkxe` | Composed shared wheel adds amendment and inline punctuation fixes with direct source/output review. Representative/largest-input capacity, corpus reparse and selected adoption remain. |
| HTML encoding and XML subsets | [ct-f6hr](../../.tickets/ct-f6hr.md) | Encoding and empty-DTD compatibility implemented. Offline malformed XML repair preserves original, diagnostics and partial candidate; missing endings stay unqualified. Cohort reconciliation remains. |
| Document/feed/error/landing roles and capture history | [ct-en4n](../../.tickets/ct-en4n.md) | Bounded role inspection and shared feed reader implemented; actual CT/Regs feed outputs reviewed. Broader role controls, zero-page classification and unresolved-source history remain. |
| Publisher refetch | [ct-z4w5](../../.tickets/ct-z4w5.md) | Deferred by the user; depends on detection/history qualification and a later decision to resume. |

## Sequence and limits

1. Keep OCR paused. The frozen recovery and follow-up OCR jobs remain stopped; the paused-resume guard stays in force. Code, tickets, retained-data analysis and native/scripted fixtures can progress.
2. Reuse the qualified mixed-version selection and interrupted-page mechanisms. Source-reviewed corrected candidates still need exposure/selection/publication qualification. A completed current attempt awaiting qualification must not be repeatedly extracted.
3. Use the composed spicy-docs candidate for ct-cbkz/ss-mkxe and ct-f6hr, retaining the merged GPO repair. The frozen non-OCR candidate inventory contains 310,964 HTML/XML bodies, 24.53 GB of original bytes and about 11.92 GB of existing text. Capture families nominate 69,609 MODS/PREMIS bodies and 9,568 meeting/witness XML bodies; resolve their roles separately from document prose before dispatch. Three larger native cases totaling 12.75 MB parsed in 1.0072 seconds at 0.26 GiB watchdog peak; independently reviewed passages retain substantive text, with table structure and source graphics still limited. This does not measure cold retrieval, actual producer batches, the largest eligible inputs or corpus throughput. Reconcile custody separately, preserving the 400 identities with `copy_usable=false`. Candidate and successful-text census populations differ. WARC requires separate payload/reachability qualification.
4. Diagnose and repair only identified bad PDF pages/bodies. Reuse qualified pre-cleanup observations where identity permits; do not re-OCR all PDFs. The 18,777-body triage set contains candidates, not that many confirmed failures. Its 146 reviewed body/page actions include controls and unresolved candidates. Do not repeat the text census or interpret it as source completeness.
5. Use maintained region, Tesseract or LLM/VLM capabilities for justified complex cases with exact settings and independent omission/value/order checks. The five conditional LLM candidate bodies have no qualified LLM results.
6. Publish qualified selections through existing gates after cohort acceptance. Retain prior readings/refusals; defer compaction. Keep publisher refetch deferred under ct-z4w5.

Operational completion and source completeness remain separate. Preserve valid empty results, old refusals and recovery evidence. Carry forward only readings proved unaffected, and declare semantic changes rather than restamping old rows. The current recovery does not silently adopt the new cleanup policy.

Two damaged-PDF source reviews also show why repair success needs content
review. One retained body contains only 1,553 bytes of a declared four-page PDF
and exposes no recoverable pages. The Walling body contains an intact earlier
nine-page revision before a truncated fourteen-page update. Its exact original
prefix `[0:336711]` is retained as a separately hashed inspection candidate;
it is not a complete replacement for the later document. A generic qpdf rewrite
passes its structural check while dropping testimony pages and blanking a
partially readable disclosure form. Named reviewers rejected that candidate.
No selection, checkpoint reuse, recognition or refetch follows from these
repairs. Evidence is under `repairs/native-pdf-repair-20261113/`.

## The large XML case is a feed

The retained `https://docs.house.gov/BillsThisWeek-RSS.xml` body is Atom despite
the filename. The hash-pinned 13 November inspection found a complete feed with
2,226 entries describing weekly House floor consideration, update times and
links to bill documents. Escaped HTML inside entries produces millions of text
callbacks. The ordinary CT page reader also refuses this body at its 24 MiB
bound; the body-text reader reaches its event bound. Neither outcome establishes
an error response or a truncated source.

The current body-text consumer refused after 1.25 seconds at 0.26 GiB peak RSS.
A temporary six-million-event measurement completed in 7.03 seconds at 1.34 GiB
RSS. No production bound changed. These measurements identify the cost of the
generic event representation; they do not justify treating the feed as one
legislative document. The prior tentative truncation interpretation is superseded.

The shared spicy-docs reader and offline CT/Regs consumers are now implemented.
Final actual outputs retain 2,226 entries and 65,511 link occurrences. CT resolves
every occurrence, including one malformed leading-slash URL whose exact target
appears in another retained entry. The original href and repair basis remain
inspectable. Direct reviews cover five entries through actual intermediate and
final outputs. The native CT replay uses 0.67 GiB/14 seconds; Regs uses
0.59 GiB/8 seconds. See [reader behavior and limits](../house-floor-feed.md).
Compare discovery coverage and verify freshness before recurring acquisition.
Scheduled consideration remains distinct from enacted status, votes or completed
actions. Neither local replay publishes a new release or starts source fetching.

Exact archived bytes, input identity and measurements are retained under
`repairs/ct-f6hr-event-limit-20261113/`. Retrieval used the retained raw archive;
no publisher refetch or OCR ran. The markup pilot and independent consumer
review are under `repairs/ct-markup-readers-20261113/`.

## Evidence and follow-on consumers

The durable local evidence root is `<main checkout>/.cache/archive-release/ocr-recovery-20261113/`. `coordination/text-quality-audit-20261113/repair-plan.md` contains the mechanism-by-mechanism design and source-review references; `repairs/ct-gpo-consumer-20261113/` contains consumer readback. The corpus/source review lives under `.cache/archive-release/investigations/text-quantity-review-20261113/`.

The finalized pause receipt at **18:32:53 UTC on 13 November** records **2,422/2,632** committed outcomes: **1,316 completed, 1,083 errors and 23 unreadable**, leaving **210** targets. Batch 206 has an interruption receipt and no committed result. `PAUSED.md`, `pause-state.json` and `pause-request.json` preserve the stop; no automatic follow-up started.

The independent audit is retained under `coordination/greybeard-root-cause-20261113/review.md`; `inventory/README.md` names the frozen CPU and targeted-page cohorts. The audit's earlier instruction to let OCR finish is superseded by the user's explicit pause. Ticket rewrites distinguish shared selection and lost page work from native coverage, geometry refusal before routing, markup adoption/compatibility, worker-lifetime RSS attribution and source-role/history gaps.

Closed `ct-chc4` covers the earlier script/JSON-LD/CSS leakage fix, not the newly identified markup and response-role gaps. Existing `ct-fk4w` owns downstream document-name/kind decisions using PDF text; `ct-m704` owns search integration. These consumer tickets remain separate from extraction-quality acceptance.

`coordination/ocr-offline-ticket-matrix-20261113.md` maps every scoped ticket to
its named direct raw/intermediate/output reviewer, exact artifacts and remaining
gate. A passing script is not that review. Bounded controls do not establish
whole-corpus completeness; missing table contents, handwriting, page-local
recognizer errors and truncated originals remain explicit source-quality gaps.
