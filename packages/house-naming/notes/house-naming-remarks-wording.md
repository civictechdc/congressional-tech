# Remarks wording and remaining descriptive structure

Decision: recognize the full remarks family and reuse existing qualifier/number
handling, then rank remaining descriptive wording for the next comparison.

Hypothesis: one shared label rule for bare Remarks and Opening, Prepared,
Written, Oral or Closing Remarks will expose printed document wording without
assigning official House codes or verified speakers. Existing contextual
qualifier handling should recover literal Final/Redacted/etc. words, preserving
dates, IDs and the original descriptive text. The complete inventory contains
102 remarks names: 90 have an Opening/Prepared/Written/Oral modifier, and 12 have
bare Remarks. Closing Remarks is a constructed extension, not observed coverage.

Arms: frozen native/strict outputs in `drafts-final`, accepted House extraction
in `calendar-wording`, and this remarks refinement. Hold all earlier guide rules,
vocabulary meanings, strict behavior and the 333,368-name corpus constant.

Cases: inspect all 102 source filenames, including dates, opaque prefixes,
query strings, repeated Final words, titles after the label, and existing
Testimony labels. Include constructed negative controls for embedded words,
structured witness slots, qualifiers separated from the label by topic words,
and date-shaped digits after a label. Do not infer document contents, author
identity, meeting access, or an official sequence from filename wording.

Intervention: append a `remarks-wording` search rule; add it to the existing
label qualifier/number pass. Keep remarks labels literal with no vocabulary code.
Reuse all existing protected-span and calendar rules. No new schema, reader,
normalization module, source download or surname list is needed.

Decision rule: accept only with exact source spans, unchanged prior fields and
metadata (except the already permitted same-span generic-number to local-number
refinement), no new readings inside assigned witness IDs, all strict outputs
unchanged, and passing full comparison/omission/preservation checks. Reuse the
existing harness and 30-minute run limit. Preserve failures and raw before/after
outputs. This corpus is reused development evidence, not an unseen accuracy test.

The remaining-wording inventory is diagnostic only. Recurring text is not
automatically a document type or an established person. Rank uncovered spans
after excluding assigned concrete fields, then inspect source examples before
choosing further semantics.

Pre-implementation boundary review: remarks labels can be followed directly by
a hearing topic. `Prepared Remarks Public Health Hearing` must not treat Public
as a qualifier. For this new family, qualifiers must precede the label in its
adjacent word group or occupy a terminal qualifier group using the existing
date/identifier-aware check. Preserve the behavior of previously qualified
questionnaire/biography labels. The initial constructed test expectation was too
permissive and is corrected before implementing the rule.

Focused correction: a qualifier can follow its label within the same terminal
group (`Remarks Final Final`). Check for a preceding label relative to the last
group member, not only before the whole group. Apply the preceding-label test
per qualifier so `Final Remarks Public Health Hearing` retains Final but does not
classify Public. Retain the first focused failure log.
