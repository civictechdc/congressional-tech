# Correct structured marker roles and hanging PDF text

Decision: fix specific structured fields currently assigned the wrong role or
left without an available source-defined meaning. Keep joined prose and bare
manager shorthand for a subsequent pass.

Hypothesis: a known legislative version followed immediately by hanging `pdf`
can retain the real version plus the existing `ignored_suffix` convention;
an exact House consideration or amendment marker in the unlisted-version slot
can reuse the existing context-specific marker rules instead of remaining an
unknown version. This improves field accuracy, not just extraction counts.

Arms: accepted `legislative-wording` outputs, frozen native/strict `drafts-final`
outputs, and the structured-marker correction. Hold the 333,368-name inventory
constant. It is reused development evidence, not an independent accuracy sample.

Cases: inventory every unknown version field and every legislative basename with
hanging `pdf` before changing code. Include all seven observed `ispdf` names,
all six joined `SUS` forms, joined `ANS`, existing separated markers, unknown
`SA`/`or`, descriptions, sponsor slots, version numbers, annotations, repeated
extensions and query tails. Add false-boundary and unsupported-format controls.
Use the catalog's retained source definition for SUS and the existing marker
rules; do not introduce a meaning for unknown SA/or or arbitrary short strings.

Intervention: extend the existing known legislative-text pattern with the
explicit hanging-pdf suffix and synchronize its exclusion patterns. Refine an
unlisted version field through the existing whole-slot House-consideration and
amendment-marker rules. Keep unrecognized tokens and source spelling unchanged.
Support the documented UConsent marker without a separating hyphen as the same
bounded known-marker case; retain the literal text and source definition.

Gate: accept only expected, explicitly reviewed field-role corrections and their
mechanically required parent rule/span changes. No strict parse behavior changes,
unrelated metadata changes, invented extensions, guessed source values or new
rule collisions. Compare every input and review every changed field; verify exact
source spans, adapter equality, existing tests and negative controls. Native
omissions must remain explained by visible replacement fields. Preserve failed
trials. Full runs retain the existing 30-minute bound.

Discovery contains 36 unknown-marker names: seven `ispdf`, six `SUS`, seven
`ANS`, fifteen `SA`, and one `or`. Expect 20 field corrections and 16 description-
only changes as the enclosing rule's explanation is clarified. All other output
must remain exact. The earlier regression test incorrectly grouped the documented
SUS consideration code with unmapped versions; replace that expectation with
source-definition and role checks, retaining the unknown SA/or controls.
