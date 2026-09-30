# Printed citations and separated measure references

Decision: determine whether explicit hearing citations and hyphen/underscore
separators can yield specific source metadata instead of generic numeric fields.

Hypothesis: reusing the existing measure vocabulary with filename separators
between its abbreviation components will recognize recurring resolution forms.
A separate printed-citation rule can expose the chamber wording, Congress and
printed citation number without equating that number with a GovInfo package ID.

Arms: frozen native and strict outputs in `drafts-final`, the accepted extractor
in `question-wording-context-qualified`, and the proposed reference changes.
Keep official definitions, strict records and the 333,368-name corpus constant.

Cases: inventory actual printed hearing/report/print citation shapes and
separated measure abbreviations first; inspect direct old/new fields. Include
embedded references, multiple references, trailing dates, protected witness IDs,
word boundaries and incomplete/malformed citation controls. Keep uncertain
spellings literal. Do not infer a publication identifier from a printed citation.

Adopt only with useful fields on source examples, exact source spans, unchanged
strict results and existing code meanings, and an explanation for every removed
field. A specific reference may replace a generic assumption at the same span;
date-like numbers inside a recognized citation should remain citation components.
Retain displaced candidates for inspection. An official meaning requires an
appropriate context; preserve unmatched surrounding titles and names.

Reuse the comparison and omission audit. Each full run is bounded to 30 minutes.
No document downloads; public source documentation may be checked. The retained
corpus and newly constructed fixtures are development evidence, not unseen
accuracy. Preserve failures and revise this note explicitly if findings require
a different intervention.

Discovery found 205 names in the separated-abbreviation candidate inventory
without any extracted measure number. Broad citation discovery also matched
existing HRPT package prefixes and testimony dates following plain `Hrg`; those
are controls, not proposed gains. Require explicit `S Hrg`, `H Rept/Rpt` or
`S Rept/Rpt` wording for a citation, respect already assigned package/person
slots, and retain printed placeholders. Actual examples include paired PDF and
URL-slug spellings from Senate Agriculture and `HRept` inside HRPT payloads.

GovInfo's hearing documentation distinguishes hearing numbers from the jacket
ID in CHRG package identifiers: https://www.govinfo.gov/help/chrg . Its report
documentation gives `H. Rept. 110-640` as a citation with Congress and report
number: https://www.govinfo.gov/help/crpt . The new source fields use
`citation_congress` and `citation_number`; no package ID is manufactured.
The 31 focused cases produced 18 failures before the change and all pass after
the first implementation. Both logs remain in the comparison cache.
