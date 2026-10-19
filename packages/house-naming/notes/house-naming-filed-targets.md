# Compound amendment filing text

Decision: extract local file identifiers, literal filing/author wording and target
references from compound legislative fields; reuse existing target refinements.

Hypothesis: full-field filing and format/target layouts expose these components
without guessing an author identity, silently fixing a name or turning a local
number into an official sequence. Explicit target slots let existing measure and
placeholder rules run without unrestricted searches through names.

Arms: saved native and strict House results in `drafts-final`, previous House
extraction in `substitute-fields-first`, and the candidate extractor. Hold the
333,368-name corpus, source definitions and native comparator fixed. Reuse the
comparison and omission-audit harnesses; retain source hashes and raw outputs.

Cases: inspect all retained legislative fields containing `filedby`, `XMLto` or
`XMLfiled`, including the Majority/Minority, XML002, missing XML, plural Reps,
misspelled Crdenas, hyphenated surnames, unknown bill numbers and spelled-out
substitute wording. Include constructed conflicting target/primary bills,
unsupported ordinals, ordinary XML words, incomplete syntax, misleading RepSoto
versus RepsTrahan wording, and non-legislative controls. The prior shortlist is
not the complete population. Leave attached names such as GrijalvaANS for a
separate boundary decision; do not hardcode surnames to increase match counts.

Accept if prior source fields and strict results remain intact, new spans are
exact, no existing code meaning is lost, and explicit target fields do not fill
missing primary metadata. Residual local identifiers and author text must stay
inspectable. Review every changed family and all field removals; constructed
cases and the reused corpus are development evidence, not an unseen accuracy
benchmark. Run one full comparison after focused controls pass, bounded to 30
minutes; repeat only to resolve a material failure. No downloads.
