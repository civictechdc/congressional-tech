---
id: ct-kfsd
status: open
deps: []
links: [ct-a73a, ct-n3ik, ct-hz8y]
created: 2026-11-13T17:46:15Z
type: task
priority: 1
assignee: mikewolfd
tags: [body_text, pdf, ocr, publication]
---
# Publish corrected historical PDF readings after GPO cleanup qualification

PR #151 is merged at 2cef1dbde71f842d527b6a9cfb8893ff8c16dc25: it preserves substantive text after printing footers and ordinary prose bullets, and adds optional per-attempt diagnostic evidence. The real CT consumer passed 14 archived PDFs / 281 pages, with exact agreement to reviewed candidate outputs. This proves bounded integration, not that historical body_text has been corrected or published. The active 2,632-body recovery deliberately retains its older frozen parser policy. Identify historical exposure, reread the affected bodies under the new declared versions, and publish qualified selections.

## Design

Reuse spicy-docs 0.85.0+gpo.20261113 and the existing CT reader, native tables and publication path. Declare PDF 4d04558965d9baf630033c94857169bfddad68988fce34041a4a35a0c6ddd2a8 and composed WARC 74403ab720b5cbbe72115d0825d928d492eff61ba27db03d01312ee7fc43c630 where applicable. The existing short-text queues are review samples, not a complete affected-body predicate. Historical rows without cleanup diagnostics remain unknown until qualified. Ambiguous printing labels such as JACKIE/WILDA are retained intentionally; removing them requires source/layout evidence. Measure diagnostic storage before broader retention.

## Acceptance Criteria

1. Freeze an exposure inventory with source hashes, affected predicates and explicit unassessed records; prove any carried-forward rows unaffected rather than globally restamping old output.
2. Restore the source-confirmed S017 tail and S055/S150/S138 bullets; retain real printing-footer, valid blank, short-page and numbered-prose controls. An independent reviewer confirms planted omissions fail.
3. Reconcile text hashes, offsets, OCR provenance, active refusals, pending work and exactly one selected version per body/parser. Qualify an actual composed-WARC cohort before claiming WARC publication acceptance.
4. Publish through the existing gates, retain the prior reading evidence and record readback of the selected corrected rows. Record diagnostics bytes and the remaining ambiguous-label limitation.


## Notes

**2026-11-13T17:46:15Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.
