---
id: ct-j9o7
status: open
deps: []
links: [ct-vq2a, ct-yci9]
created: 2026-11-05T02:36:33Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-gi01
tags: [data-model]
---

# Recover a bill package ID when the saved document supports it

Readers should be able to find a saved bill through its GovInfo package when the archive can establish the bill’s identity. A filename like `BILLS-1162899ih` leaves out the bill type. A House bill and a Senate bill can share a number, so filling in a type from the number would risk linking to the wrong bill.

## Root cause (2026-11-05)

The existing model deliberately rejects a filename-derived bill identity without a type in `model/sql/source-annotations-final.sql:10–19`. No supported candidate reached package selection for the checked document. In `e145d24c389e`, document `1a9cae0e1043a2a2` remains listed with direct source links, but both recorded source names omit type and neither it nor event `109907` carries a measure key. The audit could not locate that exact body in the two inspected local mirrors, so its identity remains unverified. The retained saved-copy replay recorded 1,587 dropped type-less IDs. That count describes exposure to the rule. The recoverable subset is unknown.

## Smallest useful change

Start with an exact retained type-less document. Use an authoritative typed GovInfo address, a typed copy of the same bytes, an explicit measure relationship to that document, or the document’s own text or title when it establishes bill type and number. Require evidence for the exact package version before publishing it. Reuse the existing package candidate selection and conflict handling. If held evidence is enough, limit recomputation to the affected document groups. Keep a package ID empty when corroboration is absent or conflicts.

## Acceptance Criteria

- A retained type-less document with independent corroboration receives the correct typed GovInfo package ID. A House/Senate number collision and a case without corroboration both leave the package ID empty.
- Existing authoritative candidate precedence and conflicting-bill protection hold. The saved document remains usable regardless of whether package identity can be established. Preserve source evidence behind accepted and unresolved identities.
- Preserve the already-working same-bytes correction from `BILLS-1181776ih` to `BILLS-118hr1776ih`. Use it as a control while checking whether any additional evidence path produces a new supported result.

## Coordination and evidence

The retained replay is `.cache/archive-release/investigations/saved-copy-identity/replay.parquet`. The same-bytes correction belongs to [ct-vq2a](ct-vq2a.md). This ticket covers document-level evidence for the remaining type-less cases. [Root-cause analysis](../docs/plans/production-mvp-root-causes-20261105.md)

## Notes

**2026-11-05T20:18:06Z**

Integrated exact-body bill evidence for document 1a9cae0e1043a2a2: its own cover and footer support BILLS-116hr2899ih. Existing authoritative precedence, House/Senate conflicts and uncorroborated cases remain protected. The paired draft PDFs are not assigned a later reported package version. Focused controls passed; candidate and selected-release verification remains due after the all-wave build hold.
