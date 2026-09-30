# Meeting-results wording

Decision: distinguish explicit meeting-results wording from general meeting/session
text without assigning an actual outcome or reclassifying unrelated topic words.

Hypothesis: context-bound prefix/suffix rules can retain `Results` as its own
field while preserving earlier meeting, access, date and name fields. Context
may include a printed numeric date, `Committee on Finance`, or the literal EBM
abbreviation. Preserve misspelled `Sessio` without silently repairing it.

Arms: accepted `project-references`, frozen native/strict `drafts-final`, and the
candidate shared-catalog rules. Keep all 333,368 names fixed.

Cases: inventory every filename containing results, inspect all distinct phrase
shapes, and check retained source associations. Include results before and after
the meeting phrase, intervening dates, plural meetings, explicit open/closed
session wording, EBM and markup. Negative controls cover educational/survey
results, long unrelated intervening prose, percent escapes and protected witness
slots. The field describes printed wording, not a verified meeting outcome.

Gate: all changed names must be reviewed discovery cases. Every prior complete
output must be identical after removing only reviewed additions. Additions must
have exact source spans without invented event status, expanded abbreviation or
vote result. Focused tests, existing tests, full comparison, typed interface,
omission audit and corpus checks must pass. Preserve failed trials. Use existing
harnesses; no downloads/dependencies. Each full run is bounded to 30 minutes.
This is reused development evidence, not independent accuracy measurement.

## Focused-test correction

The first trial passed 44 cases and failed the unrelated intervening-prose
control: a six-word committee-name wildcard consumed `Finance report about
climate trends`. Limit the optional committee text to the observed `Committee
on Finance` wording. Keep that failing negative control; a constructed Commerce
title is now an explicit unsupported form, not claimed as a validated generic
committee-name grammar. This narrows the proposed rule without changing the
corpus or the preservation gate. The first failure log remains retained.
