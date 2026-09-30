# Complete malformed numeric date shapes

Decision: prevent a fragment of malformed date-shaped text from becoming an
independent date or generic identifier while preserving the source literally.

Hypothesis: recognize a complete numeric date shape with consistent punctuation
and an unsupported three- or five-digit final component before scanning its
fragments. Retain that complete shape with a warning and no normalized date.
Do not repair source digits or assume that an extra digit is an upload suffix.

Arms: frozen native/strict outputs in `drafts-final`, the accepted extractor in
`citation-references-first`, and this shared malformed-shape rule. Hold native
code, official definitions and the 333,368-name corpus constant.

Source discovery found 368 candidate shapes, including `03.01.20231`,
`03-04-20201`, `02-14-191` and `03-09-223`. These are candidate shapes, not 368
verified dates or defects. Test actual examples plus valid dates, structured
measure/witness/publication IDs, repeated-number identifiers, trailing text and
invalid calendar components. A possible month/day order remains unspecified.

Accept if complete malformed text remains visible, no repaired calendar date is
asserted, assigned source identifiers remain protected, and displaced old date
candidates remain inspectable. Check every removed field and full before/after
outputs with the existing comparison and omission audit. Generic date-shaped
recognition is not proof of an event date. Keep the new rule limited to plausible
month/day components and a final component of unsupported length.

Use one deliberate rule addition and the existing search ordering; do not create
a second date parser. Reuse corpus and test facilities. Each full run is bounded
to 30 minutes. No downloads. These are reused development cases; preserve failed
candidates and any later revisions of these criteria.

Focused validation exposed two interactions before the full run. Six actual
`Official Hearing Transcript` names use the older labeled-date layout, which
cuts a five-digit final component into a four-digit year and suffix. Retain that
whole earlier layout in suppressed alternatives when its date field cuts a
continuous digit run, allowing the complete malformed shape to be extracted.
Apply this boundary check to both generic label/date layouts; official fixed
source slots remain unchanged. A constructed `S-Res-2-3-20231` control also shows
why explicit measure references must prevent the new malformed-date shape from
consuming an existing measure number. Reuse the existing measure regex for that
protection. Preserve the failed focused run and add regression controls.

Reject `malformed-dates-first`: the full comparison exposed 60 additional
year-first label/date layouts with a three-digit day component. Dropping those
layouts hides useful subject fields. Keep the existing label and subject fields,
extend only the partial date to its complete numeric component and adjust the
remaining suffix span. Retain the original split as a suppressed alternative.
The warning now says unsupported numeric component length because this applies
to both years and days. This explicit date-slot handling complements the free
text search; it does not repair digits or assert an event date.

Reject `malformed-dates-preserved`: its complete field review found that the
existing generic identifier `1235` disappeared from
`Poster and Handout_R&E Ligado Hearing MDG Final 1235_05-06-291.pptx` when the
trailing malformed date became protected. Reuse the existing date-remainder
helper for selected malformed shapes at either end, preserving preceding/following
text and independent numbers. Include the actual case and repeated boundary
controls. A broader year-first discovery found seven unlabelled examples of the
same three-digit day shape; extend the shared rule to those shapes as well.
No calendar correction is selected for them.
