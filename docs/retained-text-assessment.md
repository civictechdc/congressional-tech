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
| `selected`, `precleanup_available` | Selection exposure and whether the relevant intermediate is retained. Either may be null when unknown. |
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

## Cheap FTS measurements

`congress_api.cli.text_quality` supplies measured findings to the proposal layer
and a separate practical FTS review band. It can rank an existing PDF feature
generation without reopening source PDFs or retained text:

```sh
.venv/bin/python -m congress_api.cli.text_quality rank feature-generation.json \
  --out review-queue --recovery-status pause-state.json
```

The input generation names the retained baseline and incremental Parquet feature
parts and their hashes. The output `coverage-ranked.parquet` keeps reading
identities, quantities, reasons and review order. `summary.json` reports counts
by band; optional paused-recovery outcomes remain a separate population.
`review_first` and `review_later` nominate inspection, while
`no_obvious_failure_detected` means the measured checks found no obvious FTS
problem. None is a rejection or guarantee of accurate transcription. This pass
screens PDF coverage; non-PDF response roles and text garbling need their own
measurements.

For bounded cases with retained text or a native reference:

```sh
.venv/bin/python -m congress_api.cli.text_quality measure cases.jsonl \
  --out measured-cases --limit 32
```

Each case identifies its actual reading, output file/hash and reading or page
scope. Optional intermediate, original markup and feature-file references add
ordered text differences, existing response-role observations and page coverage.
Native references retain their own identity and scope; an empty native layer on
an OCR page does not imply cleanup loss. The command writes measurements and
proposals, with no OCR, network requests, selected-reading changes or repair
dispatch. Limits bound cases, files and comparisons; unsupported or unavailable
comparisons remain explicit. Use these observations to find substantial search
content loss, not to reject harmless formatting differences or every OCR typo.

## Retained demonstration and remaining work

The durable directory is
`<main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/corpus-assessment-20261113/`.
`retained-case-facts.jsonl` and `retained-proposals.jsonl` cover the reviewed
S055/S150 missing bullets, legitimate short S046 amendment and S301 edge refusal.
`data-review.md` records direct raw/native/final content observations; the
input facts are supplied by that review, not discovered by the assessor.
Focused tests separately cover wrong identities, incomplete review, missing or
conflicting stage evidence, page scope, paused routes and CLI limits.

`response-examples-20261114/examples.jsonl` adds reusable annotations for 400
existing bodies in the original `inventory/body-triage.jsonl`; it does not add
400 new bodies to the corpus. The accompanying CSV supports direct inspection.
All 400 have completed current-version HTML/XML readings. Their source roles
remain separate: 197 `NoSuchKey`, 173 House meeting-not-found and 14 House
file-not-found examples, plus 16 unmatched records. Within the unmatched group,
two previously reviewed originals provide ordinary meeting-metadata and landing
controls; the other 14 have no expected error/non-error label.

Each example preserves its archive copy descriptor, actual reading/version,
current and historical text hashes, source-review scope and frozen selection
evidence. Five existing raw-source reviews support the three template families
and two controls; the other records are not individually source-reviewed.
Use these as detector development and regression examples. Group related
templates together when evaluating new cases: 384 instances of three error
families are not 384 independent error types or a held-out accuracy estimate.
Example membership neither selects document text nor initiates refetch or OCR.

This is the bounded recommendation layer of
[the corpus assessment plan](plans/corpus-text-assessment-20261113.md).
The frozen batch-205 inventory is reconciled, and retained PDF text features
cover 296,686 bodies and 8,141,096 stored page-offset slots. Four later batch-207
outputs have separate integrity evidence and are outside that feature generation.
These results establish inventory and measurements, not source accuracy.

The current goal is cheap FTS triage: discover failed, empty, badly garbled or
substantially incomplete extraction, then directly spot-check a small sample.
Perfect transcription and a 200-body calibration study are not prerequisites.
The Keeplist applicability study is complete; its web-text threshold is
unsuitable for accepting CT documents. Keep coverage, recognition, cleanup loss
and response role separate, and reuse retained features rather than rereading the
baseline text. Unknown source fidelity does not block useful review priorities.
Actual repairs and publication remain separate. OCR stays paused and publisher
refetch stays deferred.
