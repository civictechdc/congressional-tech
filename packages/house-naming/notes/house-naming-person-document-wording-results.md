# Questionnaire and biographical wording: results

Accepted run: `.cache/filename-engine-comparison-20260929/person-wording-deduplicated/`.
Previous accepted extractor: `degree-wording-preserved/`.

**1,176 filenames now expose additional document-label metadata.** The full
333,368-input comparison adds 2,051 fields without removing an existing field or
changing any existing field's metadata. Strict parsing remains unchanged for
every input. All 2,565,831 observed field spans match the source text.

| Added field | Occurrences | Filenames |
| --- | ---: | ---: |
| Questionnaire labels and acronyms | 901 | 899 |
| Biographical labels and abbreviations | 277 | 277 |
| Printed qualifiers such as Public, Final and OCR | 810 | 515 |
| Adjacent local numeric components | 63 | 63 |

The filename groups overlap. **1,779 tests pass**, including 60 new source and
constructed cases. Generated JSON checks, ECMAScript checks and `git diff --check`
pass. The native comparator, existing extraction rules, strict schemas and
official guide definitions remain unchanged. The extraction catalog schema gains
one scope for the contextual wording rules.

## Direct before/after examples

| Filename | Previous extraction | New fields |
| --- | --- | --- |
| `Baker APQ Responses1.pdf` | Native: extension only. House: assumed name text. | Label `APQ Responses`, local component `1`. |
| `Andrew Brasher Senate Questionnaire (PUBLIC)_fb4b37e5-0157-4131-86d9-f6e3bbee9e4e.pdf` | Both retained the UUID; House also retained assumed name text. | Label `Senate Questionnaire`, qualifier `PUBLIC`; UUID unchanged. |
| `2019.SJQ.Rosen_Public_Final_421cdd79-4654-43d1-8644-cff6955963be.pdf` | Neither exposed the acronym or qualifiers. | Label `SJQ`, qualifiers `Public` and `Final`; original digits, name text and UUID retained. |
| `2023-03-08 - Bio & Testimony - Farid.pdf` | Native retained the date; House also recognized `Testimony`. | `Bio` becomes a second label; date and Testimony fields remain. |
| `Calvelli APQ Rsponses.pdf` | Neither exposed the document wording. | Label `APQ`; misspelled `Rsponses` remains unchanged rather than being silently repaired. |
| `Paul Smith CV April 2021.pdf` | Neither recognized CV; House retained generic year-like digits. | Label `CV`. Month/year precision still needs a separate date-rule improvement. |

Primary sources confirm that [SJQ is used for Senate Judiciary Questionnaire](https://www.judiciary.senate.gov/press/dem/releases/judiciary-committee-democrats-to-justice-department-provide-missing-barrett-materials)
and [APQ for advance policy questions](https://www.govinfo.gov/content/pkg/CHRG-117shrg62869/pdf/CHRG-117shrg62869.pdf).
The parser preserves the literal acronyms as labels; it does not assign them a
House guide vocabulary code or verify a particular file's contents.

Qualifier recognition uses source structure: words adjacent to a recognized
label, or a terminal group after that label followed only by delimiters, digits,
dates, opaque identifiers or a hanging pdf. `Public Health Questionnaire` does
not acquire a Public qualifier. `Public` does not establish meeting access, and
`Final` does not prove publication state. Attached digits retain their entire
source value without an inferred revision or copy sequence. Existing dates and
identifiers take precedence.

## Preservation and validation

The full field audit found **no removed fields and no changed shared metadata**.
The existing native omission audit still has no unexplained omission. Existing
House `Bio` document-type fields retain their vocabulary meanings. Existing
`Biography` labels share qualifier/number handling without duplicate labels.

The first full candidate, `person-wording-first/`, preserved all existing data but
added 22,560 redundant suppressed attempts against already typed House Bio slots.
The accepted version skips those exact duplicates. Only the 1,176 inputs with
useful field additions now change. Both runs and the focused failure logs remain
available; the first candidate is superseded, not a failed field-preservation run.

The accepted run retains full outputs, source snapshots, before/after examples,
all changed fields, `field-review.json` and `validation-manifest.json`. The field
review reuses the existing preservation checker: every earlier field and all its
metadata must survive; no new exception was needed for this iteration.

This is verified improvement on a reused development corpus, not complete
semantic coverage. Descriptive name/subject boundaries and partial dates still
need work. A new raw inventory identifies 1,189 filenames with recurring
support-letter wording for the next comparison; that is a discovery count, not
a claim of resolved people or verified relationships. Changes are local and
uncommitted, and application consumers remain unchanged.
