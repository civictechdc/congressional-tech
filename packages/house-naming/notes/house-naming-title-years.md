# Printed years in Act titles

Decision: retain explicit `Act of YYYY` references as structured literal fields
without assigning a calendar date, Congress, enactment, or document identity.

Observed: the retained inventory contains 447 names with this loose text shape.
Examples include proposed titles, historical Acts being amended, amendments
whose targets contain Act titles, and summaries. Two end in `Act-of-20182`,
where extracting 2018 would split a longer number. These are discovery inputs,
not an independent accuracy benchmark.

Hypothesis: one shared supplemental wording rule can expose the printed Act
marker and four-digit reference year. Accept separated wording and explicit
CamelCase boundaries, including acronyms followed by `Act`. Reject longer digit
runs, ordinals, ordinary word interiors, URL escape interiors, and protected
person/amendment/identifier slots. Retain repeated references independently.

Arms: the accepted `suffix-targets` extraction versus the added catalog rule.
Keep the native/strict `drafts-final` baseline as an independent historical
comparison, with the existing single reviewed Congress-boundary correction.

Before changing parser code, inspect retained source records for representative
new, historical, and amendment title references; record all predicted additions
and exact spans over the prior 333,368 complete outputs. Compare every output
after the change. Require all prior results to remain exactly unchanged after
removing only the predeclared new observations. Investigate every unexpected
change or missing addition, retaining failed trials rather than overwriting them.

Use existing source files and cached bytes only. Run positive and negative tests,
the full regression suite, the typed-adapter and span checks, native field-loss
audit, corpus mechanical checks, and catalog checks. Adopt only with reviewed
literal additions, no unreviewed losses or new false-positive controls, stable
source hashes, and passing checks. Bound each full run to 30 minutes. Repeated
corpus inputs remain development evidence. This iteration does not establish
that all filenames are semantically complete.

Pre-edit discovery predicts 892 new fields in 446 observations across 444
filenames. The other three loose matches are the two `20182` forms and an
all-uppercase `...ACIDIFICATIONACTOF2023` title with no visible word boundary.
The latter remains literal title text rather than introducing an unrestricted
word-interior search. Two filenames contain two explicit Act references.

The retained source review reads 12 inventory records and four original House
meeting-document XML entries. They confirm proposed-title wording, a historical
1991 reference, an acronym followed by `Act`, and an amendment target with two
2019 references. A Senate label separately spells 2018 for the `20182` slug;
that is context evidence, not permission to repair the filename's digits.

The first regression run passed, but an additional constructed probe exposed
uppercase terminal ordinals (`2024TH`) and punctuation after ordinals
(`2024th.v2`). The original ordinal rejection requirement was not met. Retain
those probe outputs and the first test log. The first full comparison/corpus
runs were deliberately interrupted before completion; their partial artifacts
remain in `title-years/` and `title-years-corpus/`. Add the missing catalog
boundary checks and eight regression cases, then rerun the original gates in
fresh `title-years-final/` and `title-years-corpus-final/` directories. No success
criterion or expected corpus addition is relaxed.
