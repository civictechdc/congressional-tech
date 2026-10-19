# Support/opposition filename wording: results

Accepted run: `.cache/filename-engine-comparison-20260929/support-references-punctuation/`.
Previous accepted extractor: `person-wording-deduplicated/`.

**1,197 filenames gain 3,588 source fields.** The extractor exposes 1,197 complete
support phrases, 1,197 following subjects, and 1,194 preceding subjects. These are
literal descriptive sides of the filename, not verified people, authors,
document contents or positions. Strict results remain unchanged for all 333,368
inputs. All 2,569,419 observed field spans match the original text.

| Filename | Added source structure |
| --- | --- |
| `1.10.23 - Deandre Weathersby Support for Kirsch_77e718a0-5fcb-42f2-afbd-d3a419ceecbe.pdf` | `Deandre Weathersby` / `Support for` / `Kirsch`; date and UUID stay separate. |
| `conservative-political-action-coalition-letter-of-support-for-patel` | Coalition wording / `letter-of-support-for` / `patel`. |
| `former_state_attorneys_general_letter_of_support_for_bondi1.pdf` | Group wording / `letter_of_support_for` / `bondi1`; attached digits remain intact. |
| `03 28 23 -- U.S. Support of Democracy And Human Rights.pdf` | `U.S.` / `Support of` / `Democracy And Human Rights`; punctuation survives. |
| `former-opposing-federal-prosecutors-support-for-hwang` | `former-opposing-federal-prosecutors` / `support-for` / `hwang`; “opposing” describes the contributors. |
| `strengthening-support-for-grandfamilies-during-the-covid-19-pandemic-and-beyond` | `strengthening` / `support-for` / full remaining topic; no letter or person relationship is asserted. |

The original discovery contained 1,189 filenames. The full comparison found
eight additional forms, including hearing titles and “in support of” statements.
No real opposition document occurred in this discovery; opposition cases remain
constructed tests, not measured corpus coverage.

The audit found **zero removed fields, zero changes to existing field metadata,
and no unexplained native omissions**. It reuses the existing field-preservation
checker and retains every changed output. The native comparator, previous guide
rules, vocabulary meanings and strict schemas remain unchanged.

**1,819 tests pass**, including 40 new source and constructed cases. Generated
JSON checks, ECMAScript regex checks and `git diff --check` pass. The accepted
directory retains source snapshots, comparison outputs, before/after examples,
field reviews, logs and a validation manifest.

Earlier failures remain available. The exploratory rule treated six occurrences
of “opposing counsel” or “opposing prosecutors” as extra references; requiring
explicit document wording for the verb form fixes that error. A focused test
also caught truncation inside a date-shaped bill target. The first full run,
`support-references-first/`, passed preservation checks but shortened the new
`U.S.` field to `U.S`; it is superseded. The accepted rule preserves periods,
with additional `Inc.`, `Jr.` and `.NET` controls.

This is a bounded improvement on the reused development corpus. It does not
establish complete semantic parsing. Follow-up inventories identify 73 names
with uncovered written month/year candidates and 377 names containing written
fiscal-year phrases; those are discovery counts. Changes remain local and
uncommitted, and application consumers are unchanged.
