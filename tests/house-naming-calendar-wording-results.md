# Written calendar wording: results

Accepted run: `.cache/filename-engine-comparison-20260929/calendar-wording/`.
Previous accepted extractor: `support-references-punctuation/`.

**449 filenames gain 980 fields without losing or changing existing metadata.**
The new fields distinguish written fiscal years from month/year dates. Strict
parsing remains unchanged for all 333,368 inputs; all 2,570,399 observed spans
match the original text. The native parser remains unchanged.

| Source wording | Filenames | Observations | Added fields |
| --- | ---: | ---: | ---: |
| Written fiscal year | 377 | 379 | 758 |
| Month and four-digit year | 72 | 74 | 222 |

Repeated years remain separate occurrences. The supplemental rules preserve
earlier descriptive text and fallback assumptions for inspection. They use the
existing wording scope and add no schema, dependency or download.

| Filename | Additional metadata |
| --- | --- |
| `Paul Smith CV April 2021.pdf` | Month `April`, year `2021`, month/year candidate `2021-04`; no day is invented. |
| `AELP_Bill_McGee_Written_Testimony_March2023_PDF.pdf` | `March2023` gives `2023-03` at month precision. |
| `ARL Finance Testimony March 2019 3.12.2019 FINAL.pdf` | `March 2019` stays distinct from the existing complete numeric date. |
| `Exhibit B3_Mudge moleskine + phone notes Dec 2020 Feb 2022_redacted_sanitized_opt.pdf` | Both printed month/year values survive; no interval or event role is inferred. |
| `legislative-branch-fiscal-year-24-appropriations-bill-summary` | Marker `fiscal-year`, literal fiscal year `24`; no century is selected. |
| `BILLS-117-SC-AP-FY2023-CJS-FiscalYear2023CommerceJusticeScienceandRelatedAgenciesAppropriationsBill.pdf` | The written `FiscalYear2023` inside the descriptor becomes visible alongside the existing `FY2023` appropriation slot. |

The discovery contained 250 names with month/year-shaped fragments. Of these,
177 already had complete dates. Another, `141200March2023`, has an unresolved
numeric prefix; the new rule deliberately requires an alphanumeric boundary
and leaves that source unchanged. The other 72 filenames receive partial-date
fields. Complete and invalid day/month/year readings retain precedence over
contained month/year fragments. Longer year digit runs and assigned witness IDs
do not acquire partial-date meanings.

**1,852 tests pass**, including 33 new cases. Before implementation, 18 of the
new tests failed and 15 controls passed; that log remains available. The full
comparison, omission audit and all-field preservation review pass. All 800
unique prior fields on the changed inputs retain every metadata value. There
are no unexplained native omissions, changes to existing guide rules or code
meanings, or source drift. Generated JSON, ECMAScript checks and
`git diff --check` pass.

The accepted run retains source snapshots, full outputs, every changed field,
before/after examples, all new calendar readings, the preservation checker,
test logs and a hash-verified validation manifest. Discovery files retain the
original URLs and cache origins. No network fetch was needed.

This is a bounded improvement on the reused development corpus. It does not
establish complete semantic parsing, document contents or event dates. A next
discovery identifies 90 filenames with unrecognized opening/prepared/written/oral
remarks wording; those have not yet been implemented. Changes remain local and
uncommitted, and application consumers remain unchanged.
