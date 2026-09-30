# SENR context results

Accepted as a bounded extraction improvement. Across 333,368 retained literal
filenames, 967 gained 968 SENR context observations and 3,388 fields. All 4,093
previous unique fields on those inputs retained their metadata. All strict
results stayed unchanged; 2,574,454 source spans and lossless reconstruction
passed. The 1,952-test suite, generated-file check and ECMAScript checks passed.

Added occurrences: committee token 968; committee marker 921; subcommittee token
255; subcommittee marker 248; meeting wording 962; nominations wording 14; field
marker 10; literal location token 10.

Eight retained PDFs were hash-checked and their first-page text inspected; two
pages were rendered. The subcommittee-assignment sheet and Bissell testimony
confirm that ENR in this family's subcommittee slot means Energy. NP, PLFM and
W&P/WP labels also have source-header evidence. Original spelling, including
Cmtr/Submte, stays intact. Printed context does not establish official IDs,
attendance, access, venue or event occurrence. The selected Bannon PDF was a
full-committee hearing, not the MT field hearing; no location expansion relies
on it.

Evidence: `.cache/filename-engine-comparison-20260929/senr-context/`, including
`pdf-source-review.json`, `source-documents/`, `new-field-review.json`,
`iteration-differences.jsonl.gz` and source snapshots.

The corpus is reused development evidence. This does not establish complete
semantic parsing, and later feedback separately identifies date precedence
errors outside this family.
