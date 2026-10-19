# Complete ownership of filename tooling

Decision: move the typed filename API, corpus command and its documentation
entirely into house-naming. Remove the congress_api filename modules and update
active callers. Historical snapshots and reports remain independent evidence.

Keep `Engine.extract` as the single literal reader. Retain the Pydantic result
adapter as an optional typed interface in house-naming; do not add a second
parser. The base engine still requires no Pydantic, PyArrow or congress_api.
The corpus command accepts the same Congress-keyed surname JSON as extract.
Raw legislator ingestion and conversion stay with congress_api's legislator
model; the naming package receives only the prepared vocabulary.

Remove the duplicate residual-text algorithm by using house_naming.corpus from
the corpus command's typed adapter. Keep existing output shapes and review
distinctions. Move filename unit tests with their owner; keep historical
head-to-head harnesses outside the runtime package and working against frozen
native sources.

Acceptance: direct import/CLI tests with congress_api blocked; all package and
comparison tests; full comparison against the GovInfo-publications extraction
baseline; identical extraction results; unchanged corpus data apart from source
paths and specifically reviewed residual corrections; installed package smoke
checks; no active imports of the deleted modules. Do not rewrite saved evidence
or claim semantic completion from a mechanical gate.

Category review: inspect the broad categories in the existing output files and
their representative filenames. The user narrowed this review to categories,
so further clustering analysis is out of scope. Do not add a runtime classifier
or adopt cluster numbers as document types; preserve this work as a discovery
and review aid.
