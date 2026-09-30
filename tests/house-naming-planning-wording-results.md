# Planning wording: accepted comparison

`house-naming` adds 72 literal fields across 51 filenames while preserving every
previous complete output. The additions comprise 11 budget views/estimates
phrases, 25 oversight-plan phrases, and 18 joined FY/year pairs. Existing basic
plan labels are not duplicated. A notice label can coexist with the more
specific budget phrase.

| Filename excerpt | Historical native output | Added fields |
| --- | --- | --- |
| `BudgetViewsandEstimatesFY18` | Whole suffix | `label=BudgetViewsandEstimates`, `fiscal_marker=FY`, `fiscal_year_token=18` |
| `ViewsandEstimatestext-U2` | Whole suffix plus revision `U2` | `label=ViewsandEstimatestext`; revision preserved |
| `CommitteeAuthorizationandOversightPlanih` | Descriptor plus version `ih` | Full planning-phrase label; descriptor and version preserved |

Four retained House XML entries from meetings 105639, 109042 and 115382 confirm
the source phrases. Their broad `BR` types do not convey all the meaning in the
descriptions and filenames. One short description truncates `FY18` to `FY1`,
while the filename retains both digits. The filename reader keeps `18` without
supplying a century from another source. It also preserves separate, conflicting
fiscal-year observations instead of reconciling them.

The rules describe printed wording. They do not establish committee identity,
adoption, exclusive document type or verified contents. Suspicious Activity
Reports and Short Activity Reporting appeared in the discovery but remain
unclassified by these rules; they are unrelated topic phrases.

| Verification | Result |
| --- | --- |
| Fixed corpus | 333,368 filenames |
| Focused discovery | 187 candidates; 51 changed and 136 unchanged |
| Previous complete output after removing additions | Identical for every filename |
| Strict records / typed adapter | All preserved / all equivalent |
| Source reconstruction / field spans | 333,368 / 2,577,440 checked |
| Tests | 2,610 passed, including 52 focused cases |
| Corpus mechanical gate / structural collisions | Passed / zero |
| Residual-text filenames | 3,151 → 3,138 |
| Historical native omissions | All details unchanged; 19 previously reviewed flags |
| Catalog and portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

Evidence under `.cache/filename-engine-comparison-20260929/` includes
`planning-wording/validation-manifest.json`, `planning-wording/wording-review.json`,
`planning-wording-corpus/coverage.json`, `planning-wording-source-review.json`,
and the three direct native/current examples in
`planning-wording-head-to-head-examples.json`.

This is reused development evidence, not an unseen accuracy evaluation. The
remaining review found two glued Congress references, one inside a protected
witness identifier. Their outputs and a retained amendment XML entry are saved
in the `joined-congress-*-review.json` files for further investigation. Four
damaged or truncated structured names remain incomplete. Full semantic
interpretation of every filename is not established. Changes remain local and
uncommitted.
