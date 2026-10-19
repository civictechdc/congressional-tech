# Committee-print wording and local legislative tags

Decision: recover remaining printed metadata without adding duplicate fields or
assigning a document type from a filename mention.

The previous label-only discovery found 21 committee-print names without a
label. Six already have print_token, so only 15 lack a separate phrase field.
Eight legislative filenames leave _CPTih in a broad suffix; one other preserves
CPT_01 as a descriptor with ih already parsed. Another Cpt occurrence names a
captain. Saved meeting metadata supplies legislative titles but does not establish
a universal expansion of CPT. Keep it as a raw local identifier.

Hypothesis: an additive phrase rule can expose Committee Print / Rules Committee
Print wording in free text while protecting previously assigned labels, print
tokens, person names and identifiers. Support visible CamelCase boundaries and
the observed joined ofHR/bytheCommittee continuations; do not cut Printing or
other longer words. No new print number should be inferred from nearby digits.
An early whole-field rule for CPT plus optional local number and printed ih can
operate only in assigned legislative descriptors/suffixes. Reserve its numeric
slot before generic date/member scans. Neither CPT nor its local number supplies
a document type or bill identity; ih uses the existing vocabulary lookup.

Compare the accepted companion-abbreviations-final baseline with the candidate
over all 333,368 retained filenames, plus focused positive and negative controls.
Before edits, retain the exact expected additions/spans for the discovered cases.
Require every previous output to remain identical after removing only the two
new rule observations; investigate any additional affected name against raw
source evidence. Keep the independent frozen native/strict comparison and its
existing exact Congress-boundary correction. Require typed-adapter equivalence,
native-field accounting, full regression tests and corpus checks.

No downloads, new dependencies, classifier or changes to strict naming records.
Preserve all failed trials. Bound full execution to 30 minutes and reuse cached
source evidence. This reused corpus is development evidence, not an unseen
accuracy estimate or proof that filenames describe file contents correctly.
