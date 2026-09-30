# Observed draft implementation and full-corpus comparison

House naming now recognizes **903 additional filenames**, preserving every one of
the baseline's 251,612 accepted records and their fields. This is a bounded
improvement; the objective of completely interpreting every filename remains open.

The final run is `.cache/filename-engine-comparison-20260929/drafts-final/`.
It compares both parsers on all **333,368** retained literal basenames. The native
parser's complete outputs are unchanged. The corpus is development data, not an
unseen accuracy benchmark, and includes URL routes as well as document filenames.

| Result | Count |
| --- | ---: |
| Accepted House records | 252,515 |
| PDF/XML names accepted | 217,823 / 240,623 (90.52%) |
| All document extensions accepted | 252,515 / 275,676 (91.60%) |
| Existing accepted records and fields preserved | 251,612 / 251,612 |
| Native parser outputs unchanged | 333,368 / 333,368 |
| Corpus parser exceptions / ambiguous accepted names | 0 / 0 |
| Accepted records passing canonical render/reparse | 252,515 / 252,515 |
| Tests passing | 1,040 |

## What changed

| Layout | Additional names | Extracted information |
| --- | ---: | --- |
| Absent or placeholder measure number | 195 | Explicit type, literal placeholder, stage, suffix; no invented number |
| Named draft | 105 | Draft label, local identifier, stage, suffix |
| One or more joined measure references | 206 | Every measure and its exact field-local span; optional literal SA prefix and print references |
| Numbered subject with description | 134 | Raw numbered subject, intervening description, stage; typed measure when supplied |
| Descriptive IH/PIH draft | 136 | Literal description and supported stage boundary; further structure may remain in the description |
| Subject followed by HAmdt | 86 | Raw subject and suffix, known amendment type/degree; missing bill type stays missing |
| Numbered PIH bill | 41 | Existing numbered-bill fields plus the separately defined House PIH marker |

Ordered fallback recognition protects more specific existing records. All
candidates at the first successful priority remain visible; rule order does not
choose between equally specific interpretations. The source catalog's text,
examples, definitions, committee directory, footnotes and code vocabularies are
unchanged. Generated schemas and package documentation have been updated.

## Raw checks and corrections

The first run caught a hyphenated PIH draft changing record kind after rendering.
The second caught `HRes` being split into `HR` + `ES`. Both were corrected and
covered by regression tests; the failed runs remain available for inspection.
Mixed-case `Pih` joins such as `OAWPih` now remain unaccepted with an explicit
`ambiguous-stage-boundary` issue, rather than claiming an established stage.

The retained guide's page-11 table identifies `HAmdt2` as second degree and
`HAmdt3` as third degree. Those are not amendment sequence numbers. The final
corpus contains **99 degree-bearing records**: 68 first-degree and 31 second-degree.
All 31 second-degree values agree with the independent native captures. Third
degree is exercised by guide-derived test cases. Other numeric suffixes, such as
`002`, remain literal and receive no inferred degree.

All 903 newly accepted names passed an independent Congress comparison. The
reference audit checked **997 reference occurrences in 782 filenames**:
566 measures, 284 Rules Committee Prints and 147 fiscal years. Every previously
reviewed reference remains recovered. The draft-specific audit retained the
complete native outputs for every new name and checked 457 new reference spans.
The Node portability check compiled 100 expressions and passed 54 positive
filename cases plus 54 trailing-newline rejection controls. Source hashes stayed
unchanged during the final run and its audits.

## What remains

**23,161 document filenames remain unaccepted**, along with 57,664 extensionless
basenames/routes and 28 other-extension strings. Among PDF/XML names, 1,706 have
a native outer layout, 14,250 have only partial native extraction, and 6,844 have
neither. These are different levels of missing interpretation, not interchangeable
failures. No generic opaque record was added to inflate acceptance.

Accepted descriptions also retain unresolved structure. The head-to-head audit
found **37 description differences**: 33 substitute forms and four type/title
forms. The native parser is more detailed there. For example,
`BILLS-116ANStoHR1988ih.pdf` retains `ANStoHR1988` as House naming's description;
the native parser separately identifies `ANS`, `to`, and `HR1988`. Ten newly
accepted titles also have native committee-print layouts, and 16 have local-ID
layouts. Those fields are useful candidates for the next port. Keeping their
original text avoids losing signal, but does not count as complete interpretation.

Evidence files in the final run:

- `paired-outputs.jsonl.gz`: complete outputs from both parsers.
- `upgrade-regression.json`: full baseline preservation and source-evidence checks.
- `drafts-new-records.jsonl.gz` and `drafts-audit.json`: all new records and direct field comparisons.
- `references-audit.json`: reference locations and retained independent candidates.
- `raw-degree-and-remaining-inventory.json`: degree counts and remaining groups with raw examples.
- `validation-manifest.json`: validation artifacts and their hashes.

Changes remain local; nothing was committed or pushed in this iteration.
