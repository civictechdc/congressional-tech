# Propose selective text repairs from retained evidence

`congress_api.cli.text_assessment` reads bounded JSONL facts and writes review or
repair proposals. It does not discover defects by reading a document. Existing
measurements and named direct source reviews supply the facts; the command
checks their declared identities and preserves their evidence references.
It does not open those references or verify their contents.

```sh
.venv/bin/python -m congress_api.cli.text_assessment facts.jsonl --limit 100
```

Each input line is at most 1 MiB. The default is 1,000 records and the maximum
is 10,000. Output is one JSON proposal per input. Stderr reports how many were
processed and whether further input remains unread. An invalid or duplicate
record exits with an error and identifies earlier output as partial. A bounded
run is not a complete population assessment.

## Input identity and evidence

Every fact record explicitly supplies these fields:

| Fields | Meaning |
| --- | --- |
| `body_sha256`, `parser`, `parser_version` | Exact source and actual reading identity. |
| `text_sha256`, `output_sha256` | Text identity when applicable and identity of the assessed output artifact. Null represents a missing result, not empty text. An output can be a text file or a structured role observation. |
| `source_format`, `source_state`, `reading_status` | Format; retained/missing/damaged/unknown source; completed/error/unreadable/pending/missing reading. |
| `page_number`, `page_count` | One-based PDF scope and containing page count, or null. A body-level review does not nominate arbitrary pages for OCR. |
| `selected`, `precleanup_available` | Selection exposure and whether the relevant intermediate is retained. Unknown intermediate availability is null. |
| `measurements`, `missing_measurements` | Existing scalar measurements with units in their names, and explicit gaps. No source geometry is inferred from a text count. |
| `findings` | Bounded list of `code`, `basis`, `reviewer` and `evidence` records. |

Each evidence reference has `stage`, `path`, `sha256` and `locator`. Source-review
findings require a named reviewer, raw/intermediate/output references, the raw
body hash, and the assessed output hash. This checks the declared association;
the reviewer must actually read the referenced contents. Paths and hashes alone
are not evidence of semantic qualification. Measurement and runtime findings
cannot declare themselves source-reviewed.

Supported direct-review findings include cleanup/native/recognition loss,
wrong-source and response/container/feed roles, valid empty, and source match.
The latter means preservation is justified at the stated scope; it does not
mean byte-identical transcription. Runtime findings preserve parser/geometry
refusals, invalid offsets and missing sources. Low quantity, repetition, blank
runs, mixed native/OCR gaps, possible corruption/loss and role phrases remain
measurement signals.

## How proposals differ

- `renormalize` uses reviewed cleanup loss and a retained intermediary, subject
  to its identity/coverage qualification.
- `native_reread` additionally requires a source-reviewed
  `native_reread_supported` finding. Missing pre-cleanup OCR text does not imply
  that native extraction can recover it.
- `selective_ocr` requires an exact PDF page, reviewed loss and an explicit
  `source_requires_recognition` finding. An incomplete native layer alone does
  not establish the necessary backend. OCR remains paused.
- `reparse` nominates supported markup for a qualified parser policy and later
  output review. It does not label the entire non-OCR cohort defective.
- `manual_review` retains missing stage evidence, ambiguous/conflicting findings,
  invalid page identity, or source-role/capture-history work. A known error
  response alone does not establish that the requested document is unrecoverable.
- `refetch_deferred` requires a directly reviewed unresolved source disposition;
  it remains a proposal until publisher refetch resumes.
- `keep` preserves the stated reviewed scope, or leaves an unassessed no-trigger
  result unchanged. Both remain explicitly unqualified by this tool.

Priority is ordinal from 0 to 3, higher first. It is not a probability or an
accuracy measure. `confidence_basis` describes the kind of evidence supplied;
`calibration_status` remains `not_calibrated`. Every proposal retains
`qualified=false`, `dispatch_allowed=false`, the OCR pause and refetch deferral.
The versioned assessment ID permits deterministic replay or reuse before any
source file is reopened. No proposal changes accepted selection.

## Retained demonstration and remaining work

The durable directory is
`<main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/corpus-assessment-20261113/`.
`retained-case-facts.jsonl` and `retained-proposals.jsonl` cover the reviewed
S055/S150 missing bullets, legitimate short S046 amendment and S301 edge refusal.
`data-review.md` records direct raw/native/final content observations; the
input facts are supplied by that review, not discovered by the assessor.
Focused tests separately cover wrong identities, incomplete review, missing or
conflicting stage evidence, page scope, paused routes and CLI limits.

This is the bounded recommendation layer of
[the corpus assessment plan](plans/corpus-text-assessment-20261113.md).
Current-generation inventory reconciliation, missing feature computation,
independent held-out calibration, source-qualified repair and publication
remain open. No corpus-wide classification, fresh OCR or publisher refetch ran.
