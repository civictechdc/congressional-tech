# Meeting-results wording and complete output-document review

`house-naming` now retains printed `Results` wording in 472 meeting/session
headings: 276 prefix forms and 196 suffix forms. Examples include `Results of
Executive Session`, `EBM Results`, and `Mark up 1.13.22 Results.pdf`. Existing
meeting wording, access wording, dates, identifiers and other fields remain
unchanged. The new field does not establish an actual meeting or voting outcome.

The first focused trial exposed an overly broad committee-name wildcard. It
accepted unrelated intervening prose. The corrected rule accepts only the
observed `Committee on Finance` phrase in that optional position; the failed
negative control remains in the tests. Arbitrary committee-title prose stays
unsupported. The initial failure log is retained.

Three retained download receipts confirm the reviewed filename/URL associations.
One Judiciary URL says January 12, 2022, while its redirected PDF filename says
`1.13.22`; the reader preserves the filename's date instead of reconciling it
against the URL. This review checked receipts, not PDF contents.

| Check | Result |
| --- | --- |
| Fixed corpus | 333,368 filenames |
| Changed filenames / new fields | 472 / 472 |
| Every previous complete output after removing additions | Identical |
| Typed adapter versus engine | All equivalent |
| Source reconstruction / field spans | 333,368 / 2,577,368 checked |
| Tests | 2,558 passed, including 46 focused cases |
| Corpus mechanical gate / structural collisions | Passed / zero |
| Historical native-parser omission audit | All details unchanged; 19 previously reviewed flags |
| Catalog and portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

Evidence under `.cache/filename-engine-comparison-20260929/` includes the
`meeting-results` comparison and validation manifest, `meeting-results-corpus`,
the focused discovery/preservation files, and `meeting-results-receipt-review.json`.
The corpus is reused development evidence, not an unseen accuracy evaluation.
Four damaged or truncated structured names remain incomplete. Changes are local
and uncommitted; full semantic interpretation of every filename remains unfinished.

## All output Markdown files, including the smaller-group experiment

Rechecked all **11 Markdown files, 480 lines**, recursively under `output/`.
Their paths and content hashes match the complete inventory retained in the
earlier ownership-migration review. This includes the original clustering,
segmentation, corrected committee/Congress experiment, superseded first attempt,
raw-source reviews, PDF content check and restoration note. No Markdown file was
omitted or changed. `output-category-followup.json` records the complete inventory
and fresh probes using the current reader.

The two analyses answer different questions:

- The original 56 clusters were interpreted as **21 candidate document families**.
- The later experiment measured source-label agreement against **11 broad
  categories**. It did not discover a second, finer taxonomy. Adaptive
  subcommittee/Congress grouping improved agreement from **77.84% to 84.39%**.
  Locally fitted vocabulary reached **85.66%**, but its 1.27-point improvement
  over adaptive grouping did not meet the declared 2-point advancement gate.
- The smallest committee strata had only 39 scored cases each. They do not
  establish a general accuracy rate for small groups. Adaptive fallback helped
  avoid unsupported predictions in those groups.

The current reader retains a relevant marker or phrase for the saved example
from **each of the 21 families**, including the previously missing notice and
summary wording. This is a representative-sample check, not family-wide accuracy.
The earlier review's missing notice, summary and manager's-amendment wording has
since been addressed by the accepted wording iterations.

The context review remains useful: 402 formerly unresolved filenames already had
native types, source descriptions identified Rules Committee prints and
explanatory statements, and explicit companion-format links clarified opaque
names such as `DF_004_xml.pdf`. These source associations belong with their
documents; they do not justify inventing global meanings for `DF`, `tt` or `ISO`.

The retained PDF check found two filename-supported disagreements, three
metadata-supported disagreements and one mixed document. Keep filename fields,
source types, descriptions and content assessments distinct. No classifier was
rerun or adopted as part of this review.
