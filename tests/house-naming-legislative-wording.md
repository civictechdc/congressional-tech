# Recurring legislative wording in residual text

Decision: retain explicit manager's-substitute, reported/amended/introduced/filed,
and committee-mark wording as fields instead of leaving all of it in fallback
names or descriptive text.

Hypothesis: the remaining-text audit contains recurring literal phrases that can
be extracted through shared catalog rules without assigning an official version,
document identity, committee ID or verified legislative action. Existing fields
must remain available, even when a more specific phrase is added.

Arms: accepted `partial-targets` outputs, frozen native/strict `drafts-final`
results, and the candidate wording rules. Keep the 333,368-name inventory fixed.
The corpus has been reused for development and is not independent accuracy data.

Cases: inventory every occurrence of manager, reported, as-amended/introduced/filed,
and full-committee/subcommittee-mark wording before implementing patterns. Review
all resulting spellings and changed names. Include apostrophes, separators,
joined text, numeric references, dangling pdf and query suffixes. Negative controls
must include word fragments, percent escapes, structured witness/person slots,
and longer words beginning with the same tokens. Source labels are comparison
evidence, not proof of the file's actual contents or passage history.

Intervention: extend the existing manager's-amendment rule for the explicit
substitute phrase; add literal qualifier and committee-mark wording through the
existing supplemental pass. Reuse `label` and `qualifier_wording` fields. Preserve
earlier fallbacks, number/date ownership and strict validation. Do not expand
abbreviations such as `MA`, `ISO`, `SPF` or `GSA` without their source context.

Gate: every changed name must be in the reviewed discovery, with exact raw spans,
no fabricated official codes, and no previous output removed or changed. Pass the
focused controls, full existing tests, strict/typed/native head-to-head comparison,
omission audit and corpus mechanical checks. Retain all failures and review every
unexpected change before acceptance. Full runs retain their 30-minute bound.
Do not lower the gate to accommodate a failing case.

Discovery found 854 distinct names: 406 manager-related, 332 reported-related,
18 other as-edition forms and 99 committee-mark forms (groups overlap). The
manager group also repeats explicit preamble, resolving-clause and title
amendments and manager's packages. Include those complete phrases, while leaving
bare manager wording and Pharmacy Benefit Managers topics unclassified.
Reuse the existing legislative text-slot scan for edition wording before a
version suffix, and explicitly scan a version's annotation with that same rule.
This preserves rule ownership and source offsets; it does not relax boundaries
through arbitrary joined lowercase prose. The original gate is unchanged.

The first focused check caught a percent-boundary failure in committee-mark
wording: its CamelCase alternative bypassed the percent exclusion. Apply the
exclusion before both alternatives. Preserve the failing output in
`legislative-wording-focused-first.log`; the original negative case and gate stay.
