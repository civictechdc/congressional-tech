# Recover printed House versions from separated components

Decision: use the existing stage/component readers to recover version tokens
that currently remain inside suffix text. Keep strict convention parsing and
literal source text unchanged.

Observed gaps: four filenames have a separated IH token (two PDF/XML pairs).
Four others have uppercase RSC/SCP followed by lowercase ih. Ten retained source
records confirm their bill associations; they do not establish expansions of
RSC/SCP or prove the current legislative stage. The repeated IHih names remain
unresolved for the purpose of their duplicate marker.

Hypothesis: extending the existing separated House stage marker from PIH to
PIH/IH, and generalizing the CPT reader to a visibly uppercase local component
followed by lowercase ih, recovers these tokens without guessing other word
endings. Retain CPT's existing spelling/numeric forms. Rename that reader to
local-introduction-component and use an unexpanded local-identifier note. This
removes the need to add RSC and SCP to a growing acronym list. Also preserve
standalone terminal Filed wording through the existing edition-wording rule;
it establishes no verified filing action.

Before edits, retain candidate outputs and exact expected fields/spans from the
accepted print-wording run. Compare all 333,368 names against both that run and
the frozen native/strict baseline. Require no lost source fields or changed
strict results. The permitted previous-output edits are the declared local-rule
rename/description/note and the separated-stage description update. All other
changes must be the predeclared field additions; investigate every extra case.
Check raw spans, typed-adapter equivalence, source hashes and full regression
tests. Include ordinary-word, percent-escape, assigned-person/amendment-ID and
calendar-plausible local-number negatives.

Stop after one full comparison/corpus run, up to 30 minutes, unless an observed
failure requires a retained repair trial. No downloads, new dependencies,
clustering, global acronym expansion or source-category replacement. This is
development evidence on reused inputs, not proof of semantic completeness.

Pre-edit discovery also found `BILLS-117OAWPih.pdf`. Its original House XML
explicitly records legis-num OAWP and legis-stage ih, supporting the same visible
boundary while leaving the earlier ambiguous Pih reading inspectable. The final
pre-edit inventory expects 16 new fields in nine names, plus description/rule
metadata updates in 12 previously captured names. No runtime result was used to
select these expectations.

The first inventory scan was interrupted because it copied the entire guide
inside its loop. The retained discovery script caches the guide once; it reads
the same frozen inputs and applies the same candidate patterns.
