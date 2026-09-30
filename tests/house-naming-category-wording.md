# Explicit document wording from category reviews

Decision: add useful literal filename markers identified by the global and
committee-context reviews, without introducing automatic content classification.

Hypothesis: manager's-amendment, notice/announcement, agenda and summary/component
wording can be recovered by shared catalog rules while retaining all existing
fields, fallbacks, dates, identifiers and strict naming results. Generic agenda
words in hearing topics must not acquire a document-purpose reading.

Arms: frozen native/strict outputs in `drafts-final`; accepted extraction outputs
in `complete-migration-final`; this additive wording change. Keep all prior
interpretations and the 333,368-filename inventory fixed.

Cases: the retained discovery contains 108 manager/amendment spellings, 261 names
containing notice/agenda/announcement, 179 summary/fact-sheet/section-by-section
names, and one explicit explanatory-statement name. These sets overlap and are
discovery queries, not expected match counts. Review every name and retain the
inventory. Include actual `ManagersAmendmenttotheANS`, misspelled `Amendement`,
joined number prefixes, hanging pdf, query tails, plural summaries, explicit
remote/hybrid/field notices, numbered agenda references and Trade Policy Agenda
topics. Add constructed controls for word fragments, encoded separators,
structured witness slots, errata wording and multiple document forms.

Intervention: supplemental `document-wording-search` catalog rules, preserving
earlier generic labels as well as more specific phrases. Reuse existing
protected source slots. Capture wording only; do not assign official codes,
exclusive types, verified event access, authorship or committee meanings. Keep
local `tt`/`ISO` and source-description-only distinctions outside this change.

Decision rule: all prior observations and metadata remain unchanged; strict
results and adapter results are unchanged/equal; every new field has an exact
source span and a reviewed phrase/boundary; no labels appear inside protected
identifiers or structured witness slots; no agenda-purpose reading from a Trade
Policy Agenda topic. Accept only after all tests and full corpus comparison,
omission audit and corpus checks pass. Each full run has the existing 30-minute
bound. Retain failures. The repeatedly used corpus is development evidence,
not proof of accuracy on unseen names or complete semantic interpretation.

Focused validation found four implementation failures: two manager phrases
overlapped an existing amendment marker, an underscore boundary after `of` was
rejected, and an encoded `%20` prefix appeared to supply a numeric boundary.
Allow the larger manager phrase to coexist with its existing amendment marker
while protecting the number and witness IDs; use explicit letter boundaries;
reject a percent-encoded byte boundary. The original four failures remain in
`category-wording-focused-first.log`. The decision criteria are unchanged.

Full-suite validation rejected a broader dispatch change: selecting every rule
in `document-wording-search` also ran contextual qualifiers, local numbers and
support references without their normal guards. Eleven existing tests caught
this. Restore explicit supplemental-rule selection, adding only the three new
rules. The interrupted first full comparison and corpus outputs remain in
`category-wording/` and `category-wording-corpus/`; they are rejected trials.
