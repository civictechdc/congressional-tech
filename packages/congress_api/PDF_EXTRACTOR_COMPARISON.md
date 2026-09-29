# PDF extractor comparison for witness lists

**Keep the current pypdf extractor for now.** PyMuPDF is faster on these short PDFs, but switching libraries does not fix the observed missing witnesses. Its default text order also creates incorrect person records from the member schedule. Improve the witness interpretation separately; scans need a reviewed reading or a separately evaluated optical character recognition process.

This is an offline measurement from September 28, 2026. Production code and dependencies were not changed. No network, OCR service or model calls were made.

## What was compared

- **pypdf 6.19.0:** current `page.extract_text()`, and optional `extraction_mode='layout'`.
- **PyMuPDF 1.28.2:** `page.get_text('text', sort=False)` and `sort=True`.
- Every automatic arm uses the same current `parse_document_witnesses` function. Exact-digest reviewed readings are excluded from automatic scores and measured separately.
- The strongest reference is the preceding manual visual review: **8 PDFs, 9 pages, 35 listed witnesses**, plus an abbreviated member schedule that should not create full witness records. All nine pages were rendered and inspected before this comparison.
- Throughput and native-text coverage use all **463 retained witness-list cache files**: **461 actual PDFs, 523 pages**, and two HTML error pages saved under PDF-shaped names. The broader set has no complete manual reference, so its output counts are not accuracy scores.

All PDF bytes, digests, expected readings, page text, parsed people, failures, versions, settings and timings are retained in `.cache/source-models/pdf-extractor-comparison/` at the repository root. See `experiment.md` for the criteria written before the run and the subsequently documented stricter display-field check.

## Results on the visually checked files

| Automatic extraction | Recognizable correct identities / 35 | Correct name spelling and word boundaries | Correct affiliations among identified witnesses | Invalid extra person rows |
| --- | ---: | ---: | ---: | ---: |
| pypdf default | 11 | 11 | 11/11 | 0 |
| pypdf layout | 11 | 9 | 7/11 | 0 |
| PyMuPDF default | 11 | 11 | 11/11 | 2 |
| PyMuPDF sorted | 11 | 11 | 11/11 | 0 |

Identity comparison ignores whitespace/punctuation to recognize damaged but recoverable names. The separate display-field columns preserve word boundaries and expose corruption that the identity score would otherwise hide. These selected cases diagnose known failures; **11/35 is not a corpus-wide recall estimate**.

All four modes expose the same **23 of 35 names in native text**, in the same witness sequence. The existing parser recognizes **11** of those names. The remaining **12 native-text names are in the two-page helium list without honorifics**. The parser's title/credential rule rejects them even though both libraries extracted them. The other **12 witnesses occur in four image-only scans**, which all four native extraction modes leave empty.

The existing exact-digest reviewed readings recover all **35** expected witnesses across these eight files with matching affiliations. That is a bounded manual correction for those file editions, not general automatic extraction accuracy.

Concrete reading-order and formatting differences:

- **Member schedule, event 112626:** pypdf and PyMuPDF sorted keep each time and abbreviated member name on one line. PyMuPDF default separates cells. The unchanged parser then emits `M. D. Schrier` with position `10:20`, and `Van Drew` with position `10:30`. These are incorrect records, even though the source table itself is preserved.
- **Helium, event 100266:** every mode extracts Tim Spisak, Daniel Garcia-Diaz, Kimberly Elmore and the other names correctly into text. Every automatic parser result contains only Sam Aronson, whose source line begins `Dr.`. Library replacement does not solve this case.
- **HUBZone, event 105634:** pypdf layout introduces `Shirley Baile y`, `Mansooreh Mollaghas emi`, `Acting Insp ector General`, and broken affiliation words. Default pypdf and both PyMuPDF modes preserve those fields correctly. Layout mode is not an improvement for this source.
- **Scanned immigration, agriculture, judiciary and small-business lists:** empty native text is the accurate extraction result. The original images remain in the retained PDF bytes; no arm performed OCR.

## Throughput and failure behavior

Three matched runs on the **461 valid PDFs**, with inputs already in memory and extraction order rotated:

| Extractor | Median time for 523 pages | Observed range | Valid-PDF read failures |
| --- | ---: | ---: | ---: |
| pypdf default | 2.31 s | 2.07–2.31 s | 0 |
| pypdf layout | 3.25 s | 3.14–3.49 s | 0 |
| PyMuPDF default | 0.85 s | 0.76–0.88 s | 0 |
| PyMuPDF sorted | 1.45 s | 1.39–1.46 s | 0 |

PyMuPDF default was about **2.7× faster**, saving approximately **1.46 seconds** for this entire retained cohort. Sorted extraction saved about **0.86 seconds**. These measurements exclude file reads, witness parsing, model validation, serialization and network acquisition. They do not explain a minutes-long rebuild. The initial full-cache run was faster in absolute terms, with the same ranking; both measurements are retained because concurrent machine load makes millisecond precision misleading.

All modes find **221 valid PDFs entirely empty of native text**, and 225 empty pages in total. They agree on which PDFs are entirely empty. This only describes their native text layers; an empty extraction is not evidence that a PDF contains no visible information.

The two other cache files are actual House **HTML “Not Found” pages** for events 102719 and 116051. pypdf rejects them. PyMuPDF accepts and extracts their HTML even when called with `filetype='pdf'`. Its apparent two fewer failures is therefore **not successful PDF recovery**. Preserve the existing `%PDF` input check in any future adapter, and distinguish failed acquisition from an empty scanned list.

In the broader cohort, parsed name sets differ from pypdf default in 3 files for PyMuPDF default, 23 for PyMuPDF sorted and 29 for pypdf layout. These differences are retained for inspection; they were not all visually adjudicated, and extra names must not be counted automatically as improvements. One of the three default-PyMuPDF differences is the known member-schedule regression.

## SpicyDocs reuse, checked against its actual API

The installed **SpicyDocs 0.51.0** source exposes two relevant paths, both exercised on all eight reference PDFs:

1. `spicy_docs.extraction.pypdf.PypdfReader(expected_backend_version='6.19.0')`, followed by `open(source)` and one-based `read_page(number)`. Its page strings were **exactly equal** to current pypdf default output on all eight files. It adds explicit input limits, version checking, encrypted-file policy, page-specific errors and reader lifetime handling. It does not improve text or witness accuracy. A small adapter is possible if shared reader behavior becomes useful; adding that dependency solely to fix witness misses would not help.
2. `DocumentExtractor(NativeText()).extract(source, media_type='application/pdf')`. It returns page text, geometry, source digest, line boxes and native observations using PyMuPDF with `sort=False`. This path reproduced the member-schedule problem with the same witness parser. Its native reader does not expose a `sort=True` setting. It is relevant if a later design actually uses line geometry or page regions; it is not a safe accuracy upgrade merely by replacing the current import.

No SpicyDocs or project production source was changed. Both readers leave acquisition and retention with the caller. Existing exact PDF bytes, source text, receipts and reviewed readings must survive any later implementation.

## Practical decision and limits

- **Do not switch to fix missing witnesses:** the observed misses are caused by the conservative name parser and image-only pages. Default PyMuPDF also regresses one inspected table layout.
- **Keep performance separate:** a later optional PyMuPDF backend could improve extraction speed, but the measured absolute saving is small here. It would need the existing PDF-body check and tests for reading-order changes.
- **Use the paired XML/PDF dataset for the next quality evaluation:** the separate manifest at `.cache/source-models/witness-pdf-pairs/manifest.json` supplies candidate same-meeting references. Before treating XML as expected PDF content, verify document edition, changed witness lists, panel order and supplementary/withdrawn witnesses. This comparison did not turn those candidates into automatic ground truth.
- The sample contains short retained committee PDFs. It does not qualify either library for long printed hearings, encryption, every font encoding or every table layout. No generic library ranking or corpus-wide precision/recall claim follows from this run.

## Reproduce and inspect

Run from the repository root with the existing project interpreter:

```sh
.venv/bin/python .cache/source-models/pdf-extractor-comparison/benchmark.py
.venv/bin/python .cache/source-models/pdf-extractor-comparison/assess.py
.venv/bin/python .cache/source-models/pdf-extractor-comparison/valid_pdf_timing.py
.venv/bin/python .cache/source-models/pdf-extractor-comparison/check_spicydocs.py
```

The scripts reuse the already installed matching CPython 3.12 PyMuPDF wheel and SpicyDocs source from `/Users/mikewolfd/Work/spicy-stack/spicy-docs/`; they do not install packages. Current pypdf remains the project's 6.19.0, not the older pypdf in that other environment.

Evidence files under `.cache/source-models/pdf-extractor-comparison/`:

- `oracle-inputs.json`, `corpus-inputs.json`, `inputs/`: pinned original bytes and reference readings.
- `oracle-results.json`, `strict-assessment.json`: raw page outputs, parsed people, name/affiliation scores and concrete mismatches.
- `corpus-results.json`, `corpus-timings.json`, `valid-pdf-timings.json`: all retained cohort outputs, warnings, failures and individual run timings.
- `spicydocs-results.json`: actual reader outputs and extraction settings.
- `versions.json`, `experiment.md`, and the scripts: environment, methods and scoring decisions.

The visual reference is documented in `.cache/source-models/final-manual-house-pdf.md`; its nine inspected page images remain in `.cache/source-models/manual-house-pdf/`.
