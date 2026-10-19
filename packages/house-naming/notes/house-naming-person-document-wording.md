# Questionnaire and biographical document wording

Decision: expose recurring descriptive document labels and their adjacent printed
qualifiers/numbers using the existing source-span extractor.

Hypothesis: bounded questionnaire and biography wording rules will recover labels
currently buried in assumed names, without changing strict records or existing
metadata. A deliberate bundle includes adjacent local digits and qualifier words
connected to these labels only through punctuation/spacing or other qualifiers.
Do not interpret `Public` as a meeting's access status or `Final` as verified
publication state. Do not resolve a person from surrounding name text.

Arms: frozen native/strict outputs in `drafts-final`, accepted House extraction in
`degree-wording-preserved`, and the new wording bundle. Hold the 333,368-name
corpus, native code, existing guide definitions and old source rules constant.

Discovery: the residual-word inventory inspected 37,021 descriptive filenames.
It found 458 `SJQ`, 146 `APQ`, 171 `Questionnaire` and 250 `Bio` occurrences there.
These are discovery counts, not verified defects or independent unseen cases.
The whole corpus also has many already typed House `Bio` files; their protected
source slots must not acquire duplicate labels. Full word variants and labels
may expose additional cases beyond those initial counts.

Cases: real questionnaire/biography basenames and slugs, mixed labels, UUIDs,
dates, abbreviations, response wording, qualifiers before and after a label,
adjacent copy digits and hanging pdf. Include constructed embedded-word,
unrelated qualifier, structured person-ID, short-date and multiple-label controls.
Preserve source typos instead of silently expanding them into corrected wording.

Adopt only with exact source spans, unchanged strict results, no changed guide
meanings, and an explanation for every prior field removed or metadata value
changed. Full comparison and omission audit reuse the existing harness, each
bounded to 30 minutes. Reused corpus and constructed tests are development
evidence; do not claim universal filename understanding from label coverage.

Primary source checks support treating the recurring acronyms as document-label
wording without making the parser responsible for verifying a particular file:

- The [Senate Judiciary Committee](https://www.judiciary.senate.gov/press/dem/releases/judiciary-committee-democrats-to-justice-department-provide-missing-barrett-materials)
  explicitly expands SJQ as Senate Judiciary Questionnaire.
- A [Senate hearing transcript](https://www.govinfo.gov/content/pkg/CHRG-117shrg62869/pdf/CHRG-117shrg62869.pdf)
  uses APQ for advance policy questions. The extractor will retain the literal
  acronym, not import an official House guide definition for it.

Source-inspection refinement before implementation: some files place the name
between `SJQ` and trailing `Public_Final`, and 16 observed names put copy-like
digits directly after `Public`/`Final`. Include terminal qualifier groups after
an earlier recognized label when only digits, delimiters, known identifiers,
date-shaped fields or a hanging pdf follow. Preserve adjacent digits as local
components without assigning a revision sequence. Unrelated phrases such as
`Public Health Questionnaire` still do not gain a Public qualifier.

First full comparison: 1,176 filenames gain fields, with no prior field or
metadata loss, but 22,560 other outputs gain only suppressed attempts to read
already assigned words. Nearly all are House `Bio` document-type slots. Skip a
biographical label already represented by the exact existing `document_token`,
just as for an existing label. Re-run the full comparison to measure that cleanup;
retain the first run rather than treating extra rejected matches as useful data.
