# Observed drafts and measure lists

Decision: port explicit legislative layouts and ordered fallback recognition into
House naming while preserving existing accepted records.
Hypothesis: placeholder numbers, named drafts, joined measure lists, described
numbered drafts, and House amendment markers can yield useful metadata without
inventing bill identities or treating arbitrary word endings as version codes.
Arms: saved references-final outputs versus the changed package.
Cases: all 333,368 retained basenames; actual remaining names plus constructed
negative controls. This is development data, not an unseen accuracy benchmark.
Held constant: inventory, internal parser, source catalog evidence and existing
record values. No network calls, document reads, identity dictionaries or generic
opaque records added to increase acceptance.
Decision rule: preserve every previous acceptance and field, retain every literal
placeholder and numeric token, verify reference spans and render/reparse, review
every new disagreement/ambiguity, and run the complete filename test suites.

Rules at a later parse priority run only if no earlier priority yields a validated
record. Matches within a priority remain separate; ambiguity is not resolved by
catalog order. Original conventions retain their default priority zero.
Descriptive suffixes use only IH/PIH, avoiding false versions such as Services/ES.
PIH remains a House marker, separate from the unmodified GovInfo vocabulary.

Iteration evidence: the first corpus run caught a hyphenated PIH draft whose
canonical filename selected an earlier record kind. Canonical spelling now keeps
that separator. The second run caught HRes being split into HR + ES, including
three incorrect records without multiple candidates. A longest-known-type check
now prevents that split. Mixed-case Pih joins remain unaccepted with an explicit
ambiguity issue. The retained guide's page-11 table also establishes that HAmdt2
and HAmdt3 are degrees: the implementation now exposes amendmentDegree for those
markers and preserves other numeric suffixes literally. The failed runs and raw
differences remain in drafts-current and drafts-second; neither is the final gate.
