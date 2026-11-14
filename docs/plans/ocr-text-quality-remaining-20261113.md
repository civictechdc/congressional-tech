# Remaining OCR and text-quality work — updated 14 November 2026

The GPO cleanup and optional diagnostic evidence are merged in [PR #151](https://github.com/civictechdc/congressional-tech/pull/151), commit `2cef1dbde71f842d527b6a9cfb8893ff8c16dc25`. All ten CI checks passed. Bounded integration covered 14 archived PDFs / 281 pages through the real CT consumer; independent source review approved that scope. Corrected historical text has not yet been published.

The current goal is useful full-text search (FTS): cheaply find failed, empty,
badly garbled or substantially incomplete extraction, then repair selected
cases. Perfect transcription and an LLM review of every document are not
required. On 14 November the user authorized targeted OCR and publisher refetch
to continue asynchronously. The old run stays frozen; its 206 remaining PDF
keys are running in a separate current-policy recovery lane with durable page
checkpoints. Refetch uses reviewed unresolved targets and preserves every new
response. Any bulk manual PDF/page audit uses `gpt-6.1-terra` with medium reasoning.

## Remaining work and ownership

| Work | Ticket | State and completion boundary |
| --- | --- | --- |
| Shared accepted-reading selection | [ct-55qo](../../.tickets/ct-55qo.md) | Closed after actual 14-body planner/export qualification: eight corrected readings and six unchanged actual keys. Historical publication remains ct-kfsd. |
| Durable page checkpoints | [ct-aitp](../../.tickets/ct-aitp.md) | Closed after composed checks and independent raw/checkpoint/output review. Exact-page replacement survives two late-page exits and reuses matching pages. The new authorized recovery lane is writing these checkpoints. |
| Reconcile resource failures and targeted recovery | [ct-a73a](../../.tickets/ct-a73a.md) | The old pause boundary leaves 206 PDF targets. Background recovery is now authorized; a separate current-policy lane adds durable page checkpoints and keeps old outcomes intact. |
| Publish corrected historical GPO readings | [ct-kfsd](../../.tickets/ct-kfsd.md) | Eight corrected and six unchanged actual keys are privately qualified. All 14 bodies have document associations in the checked current release; native adoption, selection and publication remain. |
| Incomplete native layers and vector text | [ct-hz8y](../../.tickets/ct-hz8y.md) | Source-qualified page coverage and selective routing remain; existing cheap signals can miss charts and bullets. |
| Native geometry failures | [ct-yy07](../../.tickets/ct-yy07.md) | Reconciled 208 affected bodies / 1,350 failed-page records. Numeric source evidence now covers four bodies / six pages; 204 bodies / 1,344 pages remain unresolved. Typed diagnostics preserve original geometry; replacement text still requires qualification. |
| Page-local recognizer crashes | [ct-t4p3](../../.tickets/ct-t4p3.md) | Qualify alternate settings on the exact failing page; shared checkpoints belong to ct-aitp. |
| Cheap extraction-failure screen | [ct-n3ik](../../.tickets/ct-n3ik.md) | Reused features cover 296,690 PDF bodies / 8,143,043 recorded slots. The final markup refresh has 45,106 candidate/control rows, including 1,182 priority 0–2 rows. Broader non-PDF signals remain. Scores rank review; they do not certify text. |
| HTML/XML reparse and adoption | [ct-cbkz](../../.tickets/ct-cbkz.md), upstream `ss-mkxe` | Reparse is complete: 310,928 successful readings, 35 refusals and one separately handled valid feed. Bounded native append and accepted selection remain. |
| HTML encoding and XML subsets | [ct-f6hr](../../.tickets/ct-f6hr.md) | Shared opt-in candidate recovery merged in spicy-docs PR #30. Direct review accounts for all 35 refusals: six useful old readings, seventeen useful private candidates, eight error responses and four damaged sources. Versioned recovery integration and actual-key adoption remain. |
| Document/feed/error/landing roles and capture history | [ct-en4n](../../.tickets/ct-en4n.md), [ct-fb7k](../../.tickets/ct-fb7k.md) | House error detection merged in CT PR #165 after all ten checks passed. Explicit reviewed source-body exclusions passed independent native review and a real two-error/one-control export replay. Broader eligibility adoption and capture history remain. |
| Publish accepted text and search coverage | [ct-m704](../../.tickets/ct-m704.md) | The checked public release has no text index, and the checked body-text export pointer returns 404. Reuse accepted retained text; do not invoke the legacy index builder's second extraction. |
| Verify source-to-search results | [ct-0a35](../../.tickets/ct-0a35.md) | After publication, check exact accepted reading hashes, substantive passages, result snippets and reopened citations through the actual consumer. |
| Publisher refetch | [ct-z4w5](../../.tickets/ct-z4w5.md) | Authorized on 14 November. The first two reviewed House targets both returned HTTP 410, with new bodies/receipts preserved; three reviewed State Department URLs are outside the published capture scope and were not requested. |

## Sequence and limits

1. Resume only the 206 remaining targeted PDF keys in a separate checkpointed lane. The frozen worker lacks page checkpoints, so restarting it would lose page work again on interruption. The maintained unlimited-size recovery policy has actual PDF version `e7af136c37deb9d3bab5a3e9f3d4c79a4f5b38bd8b8f820aba5ec175672826dc`, derived from ordinary policy `4d045589…`; neither may be used to restamp old `d6250c3c…` results. Use measured worker admission and preserve original pause receipts.
2. Reuse the frozen completed markup run. The normal lane finished at 14:50:05 UTC on 14 November: 310,528 completed and 35 refusals. Adding the separate 400-key lane gives 310,928 completed readings; the remaining inventory key is the valid dedicated feed. The run took 3h 6m 37.5s at 1.433 GiB peak RSS and produced 11,800,377,840 UTF-8 text bytes / 3,854,160,110 staged Parquet bytes. These are operational outcomes, not whole-corpus semantic acceptance. No catalog append or selection followed automatically.
3. Diagnose only residual failures. Preserve useful prior text at its actual old key. The new spicy-docs helper creates explicitly unqualified, hash-bound encoding/entity candidates; it never silently changes the default reader. Missing endings, error responses and external/recursive entity requests remain explicit refusals. Reuse existing raw/intermediate/output reviews and read new tail cases directly.
4. Consolidate the staged rows in bounded batches and append through the maintained native tables. First qualify the append memory fix and whole-generation key/identity cost under the pinned engine's 512 MiB pool. Preserve the 920 actual recovery PDF keys and eight privately qualified corrected PDF keys as separate inputs; a markup-only append does not make those rows available to an export. Keep historical refusals and one selected actual version per body/parser, without restamping.
5. Use the final exception queue, which took 1.515 seconds at 0.91 GiB peak RSS with metadata only and includes all 2,632 recovery targets and all 400 examples. Its 206 pending rows describe the old recovery snapshot; current dispatch authorization is separate. Four missing late PDF feature rows were added using 4,394,643 retained text bytes in 0.301 seconds at 0.116 GiB; all prior feature files were reused. Weak blank-page signals nominate review and do not prove failure.
6. Adopt explicit reviewed search eligibility before publication. Manifest version 2 excludes exact reviewed error/wait/feed bodies from document prose while retaining actual keys, completed evidence and full saved-body coverage. It refuses empty/unassessed roles, and exclusion cannot hide a wrong accepted digest. The real T001/T002 responses disappear from a private export while the ordinary M005 meeting control remains byte-identical. No hosted index has changed.
7. Publish qualified actual selections and an index through the existing delivery path, then complete ct-0a35's bounded source-to-search checks. The current MCP still consumes its text index; an export alone does not complete search delivery. Diagnose only identified bad PDF pages/bodies, reuse checkpoints and retained intermediates, and run the authorized targeted OCR/refetch work under separate supervision. Conditional LLM remedies have no newly qualified results.

Operational completion and source completeness remain separate. Preserve valid empty results, old refusals and recovery evidence. Carry forward only readings proved unaffected, and declare semantic changes rather than restamping old rows. New recovery results carry their actual new policy version.

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

Further geometry review retrieved three exact originals from the retained
archive, without contacting publishers. All five nominated pages contain finite,
in-page zero-width lines, but two PDFs also have truncated streams, missing-font
repairs and garbled output. The third has an invisible native span and a graphic
header missing from text. The alternate maintained PypdfReader also omits the
upper-right address on the c848 control. Native salvage must preserve original
text and diagnostic facts without inventing geometry or accepting those coverage
losses. The source-backed findings and exact unresolved identities are under
`repairs/geometry-reconciliation-20261113/`; the role proposal and producer
boundary are under `repairs/ct-markup-compatibility-20261113/role-partition/`.

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

The original pause receipt at **18:32:53 UTC on 13 November** records **2,422/2,632** committed outcomes: **1,316 completed, 1,083 errors and 23 unreadable**, leaving **210** targets. An external process later resumed; the coordinator restored the guard and stopped it at the batch-207 boundary on 14 November. Four additional completed PDFs leave **206** targets pending. Their additive integrity and feature evidence is retained separately; the old receipts are unchanged. The later explicit user authorization resumes targeted work in a separate checkpointed lane; it does not rewrite this old run.

Current evidence under `repairs/corpus-assessment-20261113/` includes
`exception-queue-20261114/final/`, the independently reviewed predecessor and unchanged builder,
`late-batch207-features-20261114/`, and `publication-state-final-20261114/`.
The checked public release is
`4b9a7bd126cc17e39dfbe7f8fabafbdb7251dcd32576277f308916f469c9bab1`,
published at 05:25:35 UTC on 14 November. Its exact detail metadata has 324,013
rows. Of the final queue priorities, 834 have unhidden document associations;
all 400 examples have none. This is association evidence, not accepted reading
or search coverage. The connector failed locally, so the public pointer and
hash-verified immutable metadata were checked directly. The export route's 404
records that route and observation time, not every possible unpublished artifact.

`repairs/markup-reparse-20261114/` retains the completed progress receipt, staged
batches, frozen final reconciliation, residual source reviews and native
adoption measurements. `adoption-planning-20261114/pdf-adoption-inputs.json`
binds the 920 recovery readings and existing 14-body private selection evidence.

The independent audit is retained under `coordination/greybeard-root-cause-20261113/review.md`; `inventory/README.md` names the frozen CPU and targeted-page cohorts. The audit's earlier instruction to let OCR finish was superseded by the user's pause, then by the 14 November authorization for the separate checkpointed lane. Ticket rewrites distinguish shared selection and lost page work from native coverage, geometry refusal before routing, markup adoption/compatibility, worker-lifetime RSS attribution and source-role/history gaps.

Closed `ct-chc4` covers the earlier script/JSON-LD/CSS leakage fix, not the newly identified markup and response-role gaps. Existing `ct-fk4w` owns downstream document-name/kind decisions using PDF text; `ct-m704` owns search integration. These consumer tickets remain separate from extraction-quality acceptance.

`coordination/ocr-offline-ticket-matrix-20261113.md` maps every scoped ticket to
its named direct raw/intermediate/output reviewer, exact artifacts and remaining
gate. A passing script is not that review. Bounded controls do not establish
whole-corpus completeness; missing table contents, handwriting, page-local
recognizer errors and truncated originals remain explicit source-quality gaps.
