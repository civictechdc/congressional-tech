# Executive business meeting wording

`house-naming` now retains 182 full Executive Business Meeting headings and
150 EBM abbreviations in results headings. Existing Business Meeting labels,
Results wording, dates, fallback text and strict records stay intact. EBM remains
an unexpanded abbreviation; its filename field does not assert a meeting type.
An explicit Open or Closed qualifier is wording, not verified access status.

This adds one guide rule, reusing the existing results-heading boundaries and
supplemental-field reader. It does not add a classifier, package dependency,
source fetch, catalog kind or external committee lookup. Generic EBM prose,
protected witness subjects and incomplete Executive Business wording do not
qualify. All 733 executive/EBM discovery candidates were compared before the
full run. Only the reviewed 332 filenames changed.

## Source checks

Two retained Judiciary PDFs explicitly say Results of Executive Business Meeting.
The June 1, 2023 receipt connects an executive-business-meeting URL with its
EBM Results PDF filename. The February 5, 2026 PDF independently confirms the
heading behind another EBM filename. All retained bytes matched receipt hashes.

The Budget download URL initially supplies an HTML wrapper, which was excluded
from PDF parsing after the first extraction failed. Its linked download receipt
leads to a separately retained PDF named `02-09-22 Budget Executive Business
Meeting3.pdf`. That PDF's heading says Business Meeting to Vote on Pending
Nominations. Its visible wording and the filename remain separate observations.
Three PDFs were inspected by native text extraction, without OCR or downloads.
This checked their first two pages, not the complete contents of every document.

## Verification

| Check | Result |
| --- | --- |
| Fixed corpus | 333,368 filenames |
| New observations / fields / changed filenames | 332 / 332 / 332 |
| Previous complete outputs after removing additions | All identical |
| Typed adapter versus engine | All 333,368 equivalent |
| Reconstruction / field spans | 333,368 / 2,577,780 checked |
| Tests | 2,683 passed; 79 focused existing/new cases passed |
| Native omission audit | Complete audit unchanged, including the 19 previously reviewed flags |
| Corpus mechanical gate / collisions | Passed / zero |
| Catalog and portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

The previously accepted strict correction for joined bill/Congress digits remains
required by the comparison harness. This iteration changes no strict result.

Evidence under `.cache/filename-engine-comparison-20260929/` includes the
`executive-business` comparison and manifest, `executive-business-corpus`,
`executive-business-focused-preservation.json`, the discovery inventory,
`executive-business-source-review.json` and the focused/full test logs.

These are reused development inputs, not an unseen accuracy evaluation.
Four damaged/truncated structured names remain incomplete, and full semantic
interpretation of every filename is still unproven. Changes remain local and
uncommitted.
