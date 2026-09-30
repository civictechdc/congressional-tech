# Recurring legislative wording: accepted improvement

The head-to-head comparison adds **692 fields across 692 filenames** while
preserving every previous complete extraction output. The change extends one
catalog rule and adds three rules through the existing extraction paths.

| Literal wording | New fields | Examples |
| --- | ---: | --- |
| Manager's amendment components | 227 | `Managers_Substitute_Amendment`, `Manager's Preamble Amendment`, `Managers_Resolving_Clause_Amendment` |
| Manager's packages | 25 | `Manager's Package`, `managers-package` |
| Edition/action wording | 341 | `As Reported`, `Reported Out`, `asfiled`, `asIntroduced`, `as_amended` |
| Committee mark wording | 99 | `FullCommitteeMark`, `SubcommitteeMarkup`, `full-committee-markup` |

These fields preserve literal wording, not verified legislative actions or
document contents. Edition wording uses `qualifier_wording`; the other phrases
use `label`. No new official code, author identity or committee identity is
assigned. Existing version tokens and their meanings remain unchanged.

The same edition rule reads a descriptive slot or parenthetical annotation
before an official version suffix, so `HR2asIntroducedih` retains both the
visible `asIntroduced` phrase and the existing `ih` interpretation. Protected
witness identifiers remain excluded from global wording searches.

The source also contains
`BILLS-119-SC-AP-FY2026-AP00-FY2026NSRPFullCommitteeMark.pdf`.
Its `SC` scope and `FullCommitteeMark` text both remain available. The reader
does not resolve that disagreement by discarding either signal.

## Evidence

- **2,296 tests pass**, including 63 new positive, boundary, protected-slot,
  conflicting-scope and existing-metadata checks.
- All **333,368** inputs were compared with the accepted `partial-targets`
  extraction and the frozen native/strict results.
- Every old observation, its ordering, metadata, suppressed candidate and
  diagnostic is identical after removing only the 692 reviewed additions.
- The typed adapter agrees with the engine for every input. No official code
  meaning changed. The native omission audit is unchanged.
- Every change occurs in the reviewed discovery and agrees exactly with the
  focused comparison. There are no unexpected changed names elsewhere.
- The corpus checks **2,576,318 field spans**, reports zero structural collisions
  and passes its mechanical gate. Source hashes remained stable during execution.
- Generated schemas, ECMAScript checks and `git diff --check` pass.

The first focused run caught a percent-boundary failure: a CamelCase alternative
could recognize `FullCommitteeMark` immediately after `%`. Moving the percent
exclusion outside both alternatives fixed it. The failed run remains in the
evidence, and its original negative test still runs.

## Remaining cases

Discovery inspected 854 names. Of those, 108 already had the relevant manager's
amendment field; 692 gain a field; 54 remain without one of these wording fields:

- **12 topic/other-reporting names** include Pharmacy Benefit Managers, asset
  managers, an externship manager and `reported to board`. They do not justify
  the new amendment, package or legislative-edition interpretation.
- **35 names use bare manager shorthand**, sometimes inside amendment IDs. They
  lack the complete phrases required by this change. Their existing references,
  local IDs and raw wording remain available.
- **Seven names have joined prose**, such as `orderedreportedvoicevote`,
  `asamendedbyEnvironmentSubcommittee` and `reportedbyagriculture`. These need
  further boundary analysis; this iteration does not split arbitrary lowercase
  words or assign a committee identity from them.

The four damaged/incomplete legislative payloads from the preceding source
review remain flagged. Default descriptor/suffix residuals decline from 3,267
to 3,258 filenames; that metric excludes much of the newly recognized wording
in fallback names. Residual text can be a valid title or name, not necessarily
a parser defect. This repeated development corpus does not establish complete
semantic accuracy or accuracy on future inputs.

Evidence is under `.cache/filename-engine-comparison-20260929/`:
`legislative-wording-discovery.json`,
`legislative-wording-focused-preservation.json`,
`legislative-wording/wording-review.json`,
`legislative-wording/iteration-summary.json`,
`legislative-wording/validation-manifest.json`,
`legislative-wording-corpus/coverage.json`,
`legislative-wording-discovery-remainders.json`, and
`legislative-wording-joined-review.json`.

Changes remain local and uncommitted. The broader filename interpretation goal
remains active; these verified gains do not settle all remaining shorthand or
ambiguous source text.
