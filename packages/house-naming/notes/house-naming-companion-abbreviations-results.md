# Bill companion abbreviations: accepted improvement

`house-naming` now exposes a literal `document_abbreviation` field in 196
filenames: 102 SxS forms and 94 MA forms. This separates useful companion-file
markers from the broader filename text. Existing bill numbers, UUIDs, source
text, fallback assumptions and strict records remain unchanged.

MA requires an existing leading Senate bill reference immediately before it.
The rule excludes Massachusetts references, the MA'O farm name and MA inside
assigned House amendment IDs. SxS also occurs after unnumbered bill titles.
Both markers support retained copy-number/UUID tails and hanging pdf text.
Neither receives an official version code, expanded label or exclusive document
type. Source context remains necessary to interpret the abbreviation.

## Source checks

The initial discovery found 56 isolated SxS filenames and 69 isolated MA
filenames. Of the latter, 54 occupy the supported bill-companion position and
15 are other uses. Saved receipts and original Senate link records were read
directly. Native text was extracted from the first one or two pages of 104
retained PDFs; 25 supplied no usable text in those pages. Two first pages were
rendered and inspected, including one of those scanned files:

- `S 3679 SXS.pdf` has a Section-by-Section heading and explanatory sections.
- `S 1414 MA_…pdf` is a scanned amendment in the nature of a substitute to S.1414.

The reviewed source supports the local companion-file pattern, not a universal
expansion of MA. Unread scanned pages remain unread. No downloads or OCR were
performed, and the original compressed PDF bodies remain unchanged.

The first full comparison found 86 additional URL basenames ending directly in
sxspdf/mapdf. The discovery scan had omitted them by requiring a boundary after
the abbreviation, although the planned parser rule allowed hanging pdf. All 86
have retained redirects to one of the original 110 reviewed PDF filenames.
Those aliases bring the expected set to 196 filename forms; they do not establish
196 distinct documents or authorize merging records.

## Verification

| Check | Result |
| --- | --- |
| Fixed comparison corpus | 333,368 filenames |
| Added fields / changed inputs | 196 / 196 |
| Other complete outputs | All 333,172 identical |
| Previous outputs after removing only the additions | All 333,368 identical |
| Typed adapter versus engine | All 333,368 equivalent |
| Field spans / original-text reconstruction | 2,578,068 spans; every input reconstructed |
| Tests | 2,821 passed, including 37 new cases |
| Native omission and fallback detail | Identical to the accepted literal-suffixes run |
| Corpus mechanical checks | Passed; zero collisions; four incomplete source payloads remain |
| Generated catalog / portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

The original failed preservation check, its expected inventory, and the expanded
source-backed inventory are retained. An initial expectation also omitted dotted
S. spellings; it was corrected using the existing normalized Senate measure code.
A later review-script assertion misstated the per-marker totals; the preserved
failure led to deriving those totals from the independent expected cases. No
parser change was needed after the full corpus exposed the alias inventory gap.

The repeated full extraction is identical to the first extraction. The corpus
run is reused because every implementation hash still matches; only the plan
amendment and two direct hanging-pdf test cases changed after that run. The
existing exact Congress-boundary correction remains the only strict-baseline
exception. These reused inputs are development evidence, not proof of complete
semantic accuracy.

Evidence is under `.cache/filename-engine-comparison-20260929/`:

- `companion-abbreviations-final/`: accepted outputs, preservation comparison,
  native audit and validation manifest.
- `companion-abbreviations-corpus/`: corpus checks against the unchanged implementation.
- `companion-abbreviations-expected-expanded.json` and
  `companion-abbreviations-slug-source-review.json`: exact expected spans and all
  86 redirect associations.
- `committee-companion-source-records.json`, `committee-companion-original-links.json`,
  `committee-companion-pdf-review.json` and `committee-companion-visual-review.json`.
- Original/final comparison and test logs; original failed review scripts and checks.

Next source-grounded gaps: 21 of 652 filenames mentioning committee prints lack
the separate wording field already captured in the other 631. Nine House files
also contain CPT beside legislative references; a tenth Cpt occurrence names a
captain. Their inventory metadata is retained for review without assigning a
global CPT meaning. Changes remain local and uncommitted; the full goal remains
unfinished.
