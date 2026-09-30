# Written fiscal years and month/year precision

Decision: expose explicit calendar wording currently left in descriptive text.

Hypothesis: two shared wording patterns can recover written fiscal years and
month/year dates while preserving their actual precision. `April 2021` must not
become April 1, and `Fiscal Year 24` must not acquire a century. Typed source IDs,
full dates, arbitrary digit runs and unknown date roles must remain protected.

Arms: frozen native/strict outputs in `drafts-final`, accepted extraction in
`support-references-punctuation`, and this supplementary wording pass. Hold the
native parser, strict parser, old guide rules and meanings, corpus and old
observations constant. The corpus contains 333,368 literal names.

Cases: retained discovery includes 377 filenames containing 379 written fiscal
year phrases, and 250 filenames with potential written month/year fragments.
Most month/year fragments already belong to full dates. Of 73 names with an
uncovered candidate, `141200March2023` has an unresolved numeric prefix and is
excluded by an alphanumeric left boundary. Review all remaining candidates.
Include repeated fiscal years, joined wording, short fiscal years, period-bearing
month abbreviations, query suffixes and hanging pdf. Construct controls for
invalid years, complete/invalid day-month-year dates, longer digit runs and
assigned witness/source IDs. These reused cases are development evidence.

Intervention: reuse `fiscal_marker` and `fiscal_year_token` for literal written
fiscal-year wording. Add `month_year_token` with a `YYYY-MM` candidate and separate
literal `month_token`/`year_token` components. Do not emit a day-level `date_token`
or infer a filing/hearing date. Run the supplemental wording after existing
extraction so original fallback assumptions and metadata remain inspectable.
Skip fragments inside already assigned concrete fields; broad descriptive text
and generic-number assumptions may be refined. Do not alter existing FY rules.

Decision rule: accept only after field/spelling/span review of every changed
input, no removed fields or altered existing metadata, unchanged strict parsing
and native code meanings, full omission audit, and passing focused/full tests.
Reuse the current comparison and preservation harnesses, each bounded at 30
minutes. Keep unsuccessful runs and any revised criteria. This does not assert
universal semantic coverage or verified file contents.
