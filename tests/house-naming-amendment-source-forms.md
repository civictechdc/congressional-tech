# Amendment identifiers in source filenames

Decision: retain numbered amendment references hidden by a hanging pdf suffix
or a compound local identifier, while protecting dates and opaque source IDs.

Hypothesis: supplement the existing native-derived amendment reference grammar
with whole compound identifiers and the already supported hanging-pdf boundary.
Keep complete identifiers such as `1v2`, and expose their local numeric component
and printed V-number without assigning a floor amendment number, GovInfo text
version, author identity or verified revision history.

Arms: frozen native/strict outputs in `drafts-final`, accepted extraction in
`remarks-wording`, and this supplementary source-form extraction. Hold existing
rules and vocabulary meanings, strict parsing and all 333,368 inputs constant.

Source discovery found 313 amendment-number candidates that neither parser fully
exposes. Manual grouping identifies 48 attached V-number cases and 156 hanging-pdf
cases. The other 109 overlap dates or opaque identifiers and must not acquire
active amendment identifiers. House source filenames include both Velazquez
`1v1` and `1v2` for the same meeting; Senate HELP download slugs use
`alsobrooks-s163-amendment-1pdf`. Retain the raw URLs and complete before outputs.

Intervention: append a supplementary amendment-reference rule using existing
`amendment_marker`/`amendment_token` fields. Reuse the late protected-span pass,
so previous generic-number/name assumptions remain inspectable. Skip existing
concrete reference fields to avoid duplicate observations. A whole identifier
matching digits + V + digits gains a local number and revision marker/number,
while preserving the complete parent identifier. Other letters remain unsplit.

Cases: all discovered examples plus constructed letter/digit identifiers,
trailing pdf and pdf-copy suffixes, invalid trailing word boundaries, overlapping
dates/UUIDs, structured witness IDs, existing sponsor IDs and plain references.

Decision rule: exact source spans, whole parent identifiers, no changes to
previous fields/metadata or strict results, no reclassification of the 109
protected candidates, and passing focused/full tests plus comparison and
omission/preservation audits. Use the existing 30-minute-bounded harness and
retain failures. No new schema or dependency is needed. This reused corpus is
development evidence, not proof of universal semantic coverage.
