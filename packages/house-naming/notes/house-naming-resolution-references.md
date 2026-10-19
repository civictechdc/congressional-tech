# Committee-resolution wording and GSA references

Decision: recover the recurring committee-resolution phrases and GSA reference
components currently retained only inside descriptive text.

Hypothesis: bounded literal rules in the shared catalog can identify committee
resolution wording and GSA/year-shaped/number references without rewriting prior
fields, assigning an actor, or interpreting reference numbers as calendar dates.
Saved House meeting 109432 explicitly retains `GSA 2018-50` and `GSA 2019-25` in
filename metadata and describes committee resolutions. That evidence motivates
the search; it does not establish every file's contents or what the year denotes.

Arms: accepted `action-phrases` output, frozen native/strict `drafts-final`
output, and the candidate shared rules. Keep all 333,368 filenames fixed.

Cases: inventory all GSA reference and committee-resolution phrase shapes before
implementation. Inspect saved XML for examples across the observed source
groups. Include word-fragment, percent-escape, protected witness-field,
calendar-plausible reference number and incomplete-reference controls. Preserve
raw spelling and exact spans. Do not expand project codes or infer dates.

Held constant: existing engine, typed adapter, corpus builder and comparison
harness. No downloads, classifier, or new dependencies. These are reused
development inputs, not an unseen accuracy benchmark. Each full run has the
existing 30-minute bound.

Decision rule: accept when every changed filename was reviewed in discovery,
all previous complete outputs remain identical after removing only the reviewed
additions, and unit, full-corpus, typed, strict and omission checks pass. Reject
unexplained changes or misleading readings. Preserve failed trials. Numeric
references must not acquire event dates, official bill numbers or resolved
project identities.
