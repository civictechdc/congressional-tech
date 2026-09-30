# Repeated label and date gaps: results

The new source rules add fields to **12,357 filenames** while preserving every
strict parsing result across the **333,368-input** corpus. They separate literal
document/meeting wording, committee-print sections, unpadded dates and date/number
components inside document subjects. Coded meanings are preserved.

The final run is `.cache/filename-engine-comparison-20260929/recurring-gaps-final/`.
The comparison retains complete native outputs and compares the changed House
outputs with the saved `extraction-named-dates` results. The intervening
context/corpus stage had verified those default outputs unchanged.

| Check | Result |
| --- | ---: |
| Inputs and strict results checked | 333,368 |
| Exact source-field spans checked | 2,554,143 |
| Inputs with additional field signatures | 12,357 |
| Inputs with additional literal labels | 5,321 |
| Additional recognized outer layouts | 1,203 |
| Inputs with date/number refinements inside document subjects | 7,671 |
| Seven-digit date candidates checked | 216 |
| Committee-print subjects recognized | 518 |
| Removed coded fields / changed shared code meanings | 0 / 0 |
| Tests passing | 1,157 |

There are 16,286 changed outputs: 12,359 have changed observations and 3,927 have
only changed records of rejected candidates. Those counts are not an accuracy
rate. The corpus remains reused development data, and several literal basenames
can refer to the same document.

## Source examples and corrections

- `brown-statement-040924` now exposes the literal `statement` label as well as
  its date-shaped text. This does not assert that the document is witness testimony.
- `official-hearing-transcript_1032018` retains four calendar readings:
  January 3, March 1, March 10 and October 3, 2018. A filename alone does not select
  the correct date order. Of the 216 seven-digit candidates, 103 have one supported
  reading, 58 have two, 43 have three and 12 have four.
- `19-13_02-14-19` now exposes `02-14-19`. Earlier scanning stopped after a
  rejected or competing prefix. The new scan considers overlapping candidates
  and prefers consistent separators; short years remain unexpanded.
- `Brown Testimony-Attachment 1_7-18-19 SENR Cmte WP Subcmte Hrg.pdf` now retains
  attachment 1 and `7-18-19` separately. The old `1_7-18` date interpretation stays
  inspectable as a rejected candidate.
- `BILLS-119-CommitteePrintSubtitleD-A000370-Amdt-116.pdf` separately identifies
  committee-print wording, subtitle D, the sponsor-shaped ID and amendment 116.
  Actual corpus matches comprise 164 plain committee-print subjects and 354
  subtitle subjects: A 47, B 36, C 24 and D 247.
- `012125-crapo-statement` retains the date, subject `crapo` and statement label.
  The first implementation exposed the label but left date/name structure inside
  a broader subject. Reusing existing date/identifier rules inside that subject
  corrected this loss of detail. Subject text remains literal, without verified
  author identity.

## Direct field review

Every native field omitted from accepted observations has an explicit audit
classification. No native omission remains uncategorized. This explains the
mechanical differences; it does not prove every interpretation semantically true.

The comparison with the previous House extractor found 91 removed field signatures
outside broad name/subject fields. All 71 generic identifiers now appear at exactly
the same spans as calendar date candidates, following the user's date-before-ID
policy. All 20 competing date spans remain in `suppressed`, with a supported
alternative retained among the observations. Each case is recorded in
`removed-field-review.json`.

The seven-digit date check independently enumerated real calendar dates and their
supported unpadded spellings, then matched every reported candidate set. All
previously verified member/title reference cases still pass. Original guide
definitions, source text, codes, examples and committee references remain unchanged.
Generated JSON checks and the existing Node schema-portability checks pass.

## Evidence and remaining work

The final run contains complete outputs, native differences, previous-House
differences, omission classifications, independent date checks, removed-field
reviews, source snapshots and a validation manifest. The first run and a failed
audit attempt are retained separately.

These rules close the sampled repeated gaps. Other broad legislative subjects,
local identifiers, abbreviated tokens and descriptive text still need review.
The native parser remains the consumer path and independent comparator; this
iteration improves the standalone House package. The full interpretation goal
remains open. Nothing was committed or pushed.
