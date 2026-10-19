# Support/opposition wording and surrounding source text

Decision: extract the recurring structure around printed support/opposition
phrases, retaining both sides as descriptive source text.

Hypothesis: one shared wording rule and boundary refinement using existing source
spans can expose the text before the phrase and its target, without surname lists,
identity resolution or source-document downloads. The raw inventory contains
1,189 support-wording filenames, predominantly from Senate Judiciary. One
Environment and Public Works filename targets a bill; an Aging hearing title
discusses support for grandfamilies. These counterexamples must not become
verified letters, authors or person-to-person relationships.

Arms: frozen native/strict outputs in `drafts-final`, accepted House extraction in
`person-wording-deduplicated`, and this support-reference refinement. Hold native
code, strict parsing, old guide rules/meanings and the 333,368-name corpus constant.

Intervention: preserve a complete `relation_wording` phrase, optional preceding
`subject_token` and optional following `target_subject`. Reuse the narrowest
existing descriptive region containing the phrase. Trim only boundary delimiters
and already assigned dates, opaque identifiers, generic/local numeric components
or hanging suffixes at the region's edges. Keep bill references inside a target.
Preserve parent text and all previous fields. Never repair source spellings,
resolve people, split arbitrary target-name digits or assert actual support.

Cases: dates and UUIDs, generic prefixes, hanging pdf, compound names/groups,
Letter of/in Support, Joint Statement wording, bill targets, ordinary hearing
titles, no source-side text, empty targets and multiple references. Constructed
controls cover opposition wording, embedded words, structured witness IDs and
independent dates/identifiers within rather than at the edges of descriptive text.

Adopt only if exact source spans and all earlier field metadata survive, no
structured source ID acquires a relationship reading, and strict results and
guide meanings remain unchanged. Reuse full comparison and field/omission audit;
each run has the harness's 30-minute bound. Inspect every family and changed
field, including the non-letter examples. This reused corpus and constructed
cases are development evidence, not proof of universal semantic coverage.

Focused refinement: a constructed date-shaped measure target exposed an earlier
fallback name boundary inside `S. 20250318`. Do not choose such a truncated
container or trim metadata spans overlapping a complete measure reference.
Preserve the full target wording while retaining all existing date/reference
candidate readings. The first focused failure log remains in the comparison cache.

The raw discovery review caught six false extra references caused by treating
bare `Opposing` as a relation: the files name opposing counsel or former opposing
prosecutors who support the target. Require a document noun for the verb form
(`Letter opposing ...`), while retaining the explicit `opposition to` form.
The complete contributor wording then stays intact. Preserve the initial
discovery outputs and add these real cases as negative/positive controls.

First full-corpus review: the broader wording rule finds eight additional files,
including a title with `U.S. Support of Democracy`. The initial boundary trimmer
removed the abbreviation's final period. Retain periods on descriptive sides;
trim spaces, underscores and hyphens only. Add the real title plus constructed
`Inc.`, `Jr.` and `.NET` controls before repeating the full comparison. The first
run preserves all older fields but is not accepted with that new-field defect.
