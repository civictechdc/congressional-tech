# GovInfo publication families and number roles

Decision: close the CPRT, CRPT and CHRG gaps identified by the user's three
GovInfo help pages, using the shared literal catalog and existing strict types.

Hypothesis: complete publication-type enums, source-specific number meanings and
early suffix reservations prevent false date readings without losing source
text, earlier citation fields or strict accepted records in the saved corpus.

Arms: frozen native/strict outputs in `drafts-final`, accepted extraction in
`congress-session-wording`, and the documented publication forms. The pre-change
probe is retained in `govinfo-help-coverage.json`. The existing corpus contains
no JPRT, WPRT or ERPT package basenames, so passing that corpus is insufficient.
Use the documented examples and constructed combinations as additional tests.

Sources checked September 30, 2026:

- https://www.govinfo.gov/help/cprt: HPRT, SPRT, JPRT, WPRT; jacket ID when
  available, otherwise print number; S. Prt. citations.
- https://www.govinfo.gov/help/crpt: HRPT, SRPT, ERPT; report numbers;
  part/volume/ERRATA suffixes. Conference status is separate metadata.
- https://www.govinfo.gov/help/chrg: HHRG, SHRG, JHRG; jacket IDs;
  part/volume/err suffixes. The page uses err for both addenda and errata;
  preserve that ambiguity in the literal field's explanation.

The report help page contains a CPRT example under its CRPT formula and labels
an .htm link XML. Do not adopt those contradictory examples as new rules.

Intervention: extend the three literal publication rules to every documented
type and one-to-three-digit Congress values; add WPRT to the strict print enum.
Retain raw publication-number strings and add their source-specific meanings.
Recognize full suffix words alongside existing aliases inside publication
suffixes, before generic numeric scans. Preserve earlier part-token behavior
where it already provides fields. Extend printed citations to S. Prt. Keep all
filename extraction regexes in guide.json. Update generated schemas and docs.

Held constant: input inventory, House-guide source transcription, unrelated
rules, strict records for existing corpus inputs, and no new source downloads.
Each full comparison is bounded at 30 minutes. The existing corpus is reused
development evidence; constructed source cases are not observed corpus counts.

Decision rule: require both APIs to expose the documented types, no numeric
identifier reclassified as a date, exact source spans/reconstruction, meaningful
positive and rejection tests, adapter equality, no unexplained field loss,
unchanged strict corpus results, and no structural collisions. New labels,
number-role notes and source URLs are intended metadata additions. A scoped
suffix interpretation may displace an overlapping generic date/identifier or
fallback, but its entire source and the reason must remain inspectable. Review
all changes, including metadata and any suppressed alternatives. Full semantic
understanding of every filename remains unproven.
