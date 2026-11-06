# Congress Archive standard catalog

These ODCS 3.2.0, ODPS 1.1.0 and DDK declarations preserve the archive's original 254
physical fields, declared identities, 70 relationships and 16 DuckDB recipes.
`project.ddk.json` binds the definitions, relationships and recipe files through
the maintained DDK catalog API. Recipe `inputs` are executed requirements;
`contextualRelationships` are explanatory references. `parameterOrder` states
the order of positional SQL values. Native lake schemas and field IDs remain
owned by `model/lake`; virtual row positions belong to catalog identities.
The current public shape adds three capture eligibility fields: required
`capture_disposition` and `capture_reason`, and nullable `capture_decision_id`.
Its 257 fields require an explicit policy-bound capture profile version 2. The
capture SQL retains the existing eligible/satisfied/excluded decisions; no value
is invented for a version 1 or policy-free input. Retained version 1 row fixtures
exercise metadata/readers only and do not establish this complete current shape.

Meanings, coverage limits, nullability explanations and field notes live in
standard ODCS descriptions and required flags. Nested logical structure and
scalar physical types survive the maintained public disclosure view. Recipe
titles, notes and contextual relationships stay on their DDK records. The scoped
upstream-relations extension describes external SpicyRegs tables. There is no
reverse schema converter, legacy JSON ordering map or application definition
validator in the discovery path.

`ddk.catalog.assemble_catalog` returns an admitted catalog, exact companion bytes
and the complete checking report. Unsupported relationship semantics remain
unknown until a maintained profile supports and qualifies those rules. Exact
candidate-bound native evidence is a separate requirement; it cannot turn
unsupported semantics into a passed check. Only a passed result exposes the
standard `artifacts` bytes. Public definitions require explicit field grants;
project extension grants bind the exact source project identifier and version.

Both applications require the public catalog, report and lock. MCP discovery
reads admitted definitions and typed relationships directly, and resolves SQL
from verified recipe companions. Browser `catalog()` returns the standard
record unchanged and caches metadata reads. Neither application accepts legacy
`schema.json` metadata, old custody stamps or a second decoder. Recipe and
relationship selectors use their published full identifiers. Metadata checking
is reported as `catalog_checking`; it does not establish data qualification.

The sole `finalize_native_release` function receives exact prepared controls
and optional post-execution catalog artifacts. It preflights the complete
control and manifest byte set before writes; identical retries keep file
custody, changed controls refuse, and missing identical controls can finish a
partial attempt. The managed caller must retain schema/check definitions,
diagnostics, extra outputs, artifact bytes, origin, capture controls and entity
generation digests, and bind the protected native output directory and result
bytes. This source seam does not adopt a recovery controller. Native physical
job guarantees remain until authoritative DDK definitions and the supported
application profile replace their current owner; final public control emission
is being coordinated with that profile.

Independent semantic expectations were frozen from Git source
`a06eb64bf3caa4a44e12a89bdd08939323de3092`. They protect domain fields, grain,
relationship scope and recipe inputs. Test fixtures use genuine DDK public
assembly with explicit grants. The complete public catalog now passes MCP and
browser discovery, verified SQL delivery, comparison and publication checks;
current-field tests distinguish missing optional tables, malformed current data
and empty results. These checks do not qualify a replacement-produced native
release. Full replacement acceptance,
exact native data binding and the complete source/consumer journeys remain
separate obligations.
