# Reuse known component rules in legislative suffixes

Decision: recover structured data in suffixes without treating every remaining
title or acronym as an unresolved parsing failure.

Observed: six reported-bill filenames retain p1/p2/p3 only in their suffix. Their
three saved bill XML bodies and PDF opening pages describe distinct committee
versions, with unassigned report-number placeholders. Keep the literal p marker
and identifier; do not invent an official report number or establish what the
number identifies. Reuse publication-suffix-marker rather than asserting the
stronger report-part meaning.

Three more filenames state explicit substitute targets. Two original meeting
XML entries spell out AINS to HR 1759/1994. The third states ANS to HR3633 and
offeredbyChairmanThompsonofPennsylvania. Its PDF opening confirms that printed
heading, while the meeting description says withdrawn. Filename wording cannot
establish action history or a person's identity.

Hypothesis: apply the existing whole-slot substitute-target reader to owned
legislative descriptors/suffixes, allowing their leading separators. Extend its
measure-target form with explicit offeredby text and an optional terminal U
revision, preserving the offering marker and offerer text separately. Parse the
numeric slots before generic dates. Apply the existing publication suffix rule
to numeric p components of explicitly reported House/Senate bill suffixes.
Retain all existing observations; avoid duplicate already-known target matches.

Before edits, record candidate additions and spans over the accepted
version-components outputs. Compare all 333,368 filenames against that run and
the independent frozen native/strict baseline. Require original fields,
meanings, strict results and literal reconstruction to remain intact except for
an explicitly reviewed correction. Investigate every unplanned output change.
Test calendar-plausible target numbers, update tails, assigned person/amendment
slots, ordinary word endings and unsupported partial offeredby forms.

Use the retained corpus, meeting XML and cached document bodies. No downloads,
OCR, new dependencies, name-resolution assumptions or source-status replacement.
Run the full regression suite, typed-adapter/span checks and corpus mechanical
checks. Bound each full run to 30 minutes; preserve failed trials and source
hashes. Reused inputs are development evidence, not unseen semantic accuracy.

The pre-edit complete-output scan found one additional spelled-out form,
`BILLS-114207rfh-AmendmentintheNatureofaSubstitutetoHR207-U1.pdf`.
The recorded expectation is 30 new fields across ten filenames. First-page
native text was reviewed for four cached PDFs and two first pages were rendered
and inspected; three cached bill XML openings and six original meeting-document
subtrees were also read. The reported-bill covers leave their report numbers
blank, reinforcing the decision to retain p identifiers without official roles.
