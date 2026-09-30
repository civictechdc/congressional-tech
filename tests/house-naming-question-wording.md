# Questions-for-the-record wording and hanging format suffixes

Decision: expose recurring question/answer document wording and labels obscured
by a hanging pdf suffix, using the existing literal-label and subject machinery.
Explicit subject refinements must retain hanging-suffix fields from the same
fallback policy, so recognizing a label cannot hide previously exposed suffixes.

Hypothesis: sharing the additional QFR/Questions for the Record phrase forms
across the existing label-only, label/subject and search rules yields useful
labels and subject fields without inferring document contents, person identity
or official source codes. Recognizing an existing document label before terminal
pdf text restores a signal already present in the raw filename.

Arms: frozen native/strict outputs in drafts-final, the accepted House extractor
in statement-dates-reviewed, and this deliberate wording bundle. Hold the native
parser, official guide definitions, strict records and recovered 333,368-name
corpus constant. The development inventory contains 3,690 QFR substrings, 647
full questions-for-the-record phrases and 474 terminal label+pdf names; these are
candidate counts, not anticipated gains. Source rows and the corpus-wide residual
ranking are retained in document-wording-inventory.json and remaining-rank-20260929.json.

Cases include plural/possessive QFRs, responses/answers before or after QFR,
written questions/responses, joined QFRResponses, hanging pdf, dates and UUIDs
adjacent to labels, and structured House document/name fields. Counterexamples
include QFR inside longer words, record vs recording, ordinary response titles,
nonterminal pdf text, and unprinted years or person identities.

Accept only if added labels match exact literal wording, dates/identifiers and
strict results retain their existing values, official code meanings do not
change, and every changed old field is retained or explained by an explicit
label/subject split with source spans. Broad subject text is not proof of full
interpretation. Inspect the full comparison and field losses, not just new match
counts. Reuse the existing comparison and omission audit; retain failed runs and
source hashes. Each full run is bounded to 30 minutes. No downloads.

The corpus is reused development evidence. Generic responses and final/draft
words inside titles do not alone establish a document category or publication
state and are outside this intervention.

Full-corpus correction: reject question-wording-first. One previously extracted
terminal generic identifier is lost when Responses-to-Questions-for-the-Record-1-Lazarus-1
becomes an explicit subject: the shared fallback recognizes only the leading 1.
Reuse that same fallback on its progressively shorter name/subject remainder,
preserving both numeric components, dates and the full parent text. Add the actual
regression and constructed repeated-prefix, trailing-date, protected-reference and
bounded-input controls before rerunning. The original outputs and this failure
remain retained; do not add a special case for Lazarus or reinterpret its numbers
as official question/document sequences.

Stronger reference control: S42, S 42 and S-42 must all retain the recognized
measure number without gaining a generic-identifier assumption. Consolidate
accepted specific field spans before the final fallback; fields found by free-text
reference searches deserve the same protection as initial structured slots.
Any existing generic assumptions displaced by those specific fields must be
accounted for directly by matching raw value and source span, with their source
text retained in the broader name/subject. This protection applies to the shared
fallback, not just the new question labels.

Date-selection correction: reject question-wording-reviewed. The recursive
fallback revived mixed-separator candidates such as 13_02-14 inside the actual
19-13_02-14-19 filename, crossing the already selected 02-14-19 date. Calendar
plausibility alone is insufficient. A fallback date overlapping an assigned token
must exactly match an already selected numeric date span; otherwise leave it
suppressed and continue the established fallback policy. Apply the same check
to explicit subjects and root/remainder fallbacks, and retain the original
global date alternatives. Add actual and constructed overlap regressions.

Manual semantic correction: do not accept question-wording-date-guarded merely
because its field-loss accounting passes. Three source contexts expose wrong
existing date selections: Addendum 2 followed by 3-29-22, revised_1262022, and the
same-month range June 9-10, 2021. Recognize an explicit addendum number followed
by a complete valid date before overlapping numeric scans; reuse existing compact
date recognition after revision wording; recognize printed month/day ranges with
four-digit years before their contained month/day fragments. No event-date role,
missing century or corrected source digits may be inferred. Invalid ranges retain
their components and warning; valid ranges have a single normalized start/end
interval candidate. Inspect all changed source cases, including the 27 addendum
number discoveries, three range names and compact-revision candidates retained in
question-wording-date-contexts.json. Retain all prior failed runs and their audits.

Fixture correction: 1262022 permits January 26, June 12 or December 6 under the
already supported unpadded month/day layouts. The initial test incorrectly chose
only January 26. Keep all three literal calendar readings, as the original policy
requires; no parser change was made to reduce those alternatives. The initial
test failure remains in question-wording-context-after.log.
