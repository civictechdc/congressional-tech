# Question wording and date context: results

Accepted run: `.cache/filename-engine-comparison-20260929/question-wording-context-qualified/`.
Previous accepted extractor: `statement-dates-reviewed/`.

The full comparison checks **333,368 literal filenames and URL basenames** from
the recovered local inventory. Strict parse results remain unchanged for every
input. All **2,563,204 field spans** match the original text. The native parser,
existing vocabulary meanings and official guide definitions remain unchanged.
**1,601 tests pass**, including 87 additional cases since the previous accepted
run. Generated JSON, ECMAScript checks and the field-loss audit pass.

## What changed

**3,681 filenames gain or refine fields.** Another 1,424 outputs change only
their retained alternative matches; 5,105 outputs change in total.

| Change | Observed effect |
| --- | --- |
| Question/answer wording | 722 new labels containing QFR abbreviations and 649 containing questions-for-the-record wording. |
| Labels before terminal `pdf` text | 473 new labels, including testimony and opening statements. No file extension is invented. |
| Repeated prefix/suffix extraction | The existing fallback can expose additional numeric components and dates in progressively shorter remainders while retaining the parent text. |
| Protection for specific fields | 417 bill-number fields, 182 amendment fields and 47 item fields displace generic numeric assumptions at the exact same source spans. |
| Addendum/date separation | Three source names retain addendum number `2` separately from `3-29-22`. |
| Written date ranges | Three source names retain both days of `June 9-10, 2021`, with interval candidate `2021-06-09/2021-06-10`. |
| Revision/date separation | `testimony_rainey_revised_1262022` no longer simultaneously presents the digits as an active revision number and date. All three supported date readings remain. |

The 1,844 new label occurrences appear in **1,842 filenames**; counts overlap
where a name contains multiple labels. They describe literal filename wording,
not verified document contents or person identities.

Examples:

| Filename | Extracted information |
| --- | --- |
| `Wagner Responses to QFRs1.pdf` | Label `Responses to QFRs`, descriptive subject and numeric suffix. |
| `greenstein-responses-to-qfrspdf` | Label `responses-to-qfrs`; the original spelling and hanging `pdf` remain available. |
| `canterbury-testimonypdf` | Literal `testimony` label without inventing an extension. |
| `Responses-to-Questions-for-the-Record-1-Lazarus-1.pdf` | Explicit question-response wording, both numeric components and remaining subject `Lazarus`; no resolved identity or official sequence number. |
| `Haynes Testimony Addendum 2 3-29-22.pdf` | Addendum number `2`, date-shaped token `3-29-22`; no inferred century. |
| `Results Of The Open Executive Session Of June 9-10, 2021.pdf` | Both day components, printed year and a validated interval candidate. |
| `testimony_rainey_revised_1262022` | Revised wording and candidates `2022-01-26`, `2022-06-12`, `2022-12-06`; no selected event date. |

## Checks and corrections

The field review accounts for every removed field. It checks that 1,497 prior
name/subject fields remain covered by more explicit source fields; 647 generic
assumptions become specific fields, including one range year; and 59 replaced
candidate fields remain verbatim in `suppressed`. One revision-marker note gains
the documented date clarification. Its exact previous metadata remains in the
suppressed original revision match; all other attributes are unchanged.

The generic remainder pass adds 1,486 numeric fields under the existing fallback
policy. These remain assumptions. The 82 added `date_token` fields are not 82 new
dates: some repeat an already extracted `short_date_token` at the same span.
New numeric fields cannot overlap assigned specific fields. New fallback dates
cannot cross an assigned date or identifier; an overlapping date must have the
exact span of an already selected date.

Manual inspection covered the added date fields, all discovered date-range,
addendum and compact-revision contexts, the revision-note change, and a fixed-seed
sample of added labels, numeric assumptions and hanging suffixes. Full automated
comparison is broader than this manual sample; neither proves unseen accuracy.

Three earlier candidates remain rejected and retained:

- `question-wording-first/`: recognizing a new explicit subject lost a trailing
  numeric component. Shared remainder extraction fixes it.
- `question-wording-reviewed/`: remainder extraction revived overlapping date
  fragments. Shared date-span protection fixes it.
- `question-wording-date-guarded/`: mechanical checks passed, but manual review
  found the addendum, revision and date-range interpretation problems above.

The initial date-context test incorrectly selected only January 26 for
`1262022`. The corrected fixture retains all supported readings. The original
failure is retained; the parser was not narrowed to satisfy the incorrect test.
The initial field-review flag is also retained, alongside the exact before/after
revision fields and the narrowly qualified reviewer check.

## Limits and next gaps

This is an accepted improvement on reused development data, **not complete
semantic interpretation**. All characters remain recoverable, but preserving
characters and emitting a generic assumption do not establish their meaning.
The native application consumers are unchanged. Work remains local and
uncommitted; this iteration fetched no documents.

Manual samples identify useful next work:

- Printed citations such as `S. Hrg. 115-693.pdf` still expose generic numeric
  components rather than a hearing citation.
- Some hyphenated measure spellings, such as `s-res-206-062519`, leave a bill
  number generic. They need comparison with the existing measure rules.
- Malformed numeric sequences such as `Transcript_03.01.20231.pdf` retain an
  existing short-date candidate for `20231`. No repaired year or event date is
  emitted, but that candidate can still be misleading. This batch does not fix
  the older numeric-date interpretation.
- Ordinary names, titles and local identifiers remain partly uninterpreted.
  The ZIP name `offered.zip` has no non-extension semantic observation.

`iteration-differences.jsonl.gz` retains full before/after outputs for all 5,105
changes. `candidate-review.json`, `field-review.json`, `omission-audit.json` and
`revision-date-review.json` hold the review evidence. `validation-manifest.json`
and `final-checks.json` record exact source hashes and qualification limits.
