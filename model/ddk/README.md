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

Qualified dev6 supplies `.local_catalog` and `.local_report` for complete private
writer checks, alongside audience-filtered `.catalog` and public artifact bytes.
The native invariant adapter uses the complete private view from that same
assembly. It does not assemble or read the definitions a second time. A public
policy can withhold field details and identities without removing required native
checks. Composite native type text requires an explicit `definitionPhysicalTypes`
grant as well as disclosure of every modeled child; that disclosure does not
qualify native type mapping or actual data.

Both applications require the public catalog, report and lock. MCP discovery
reads admitted definitions and typed relationships directly, and resolves SQL
from verified recipe companions. Browser `catalog()` returns the standard
record unchanged and caches metadata reads. Neither application accepts legacy
`schema.json` metadata, old custody stamps or a second decoder. Recipe and
relationship selectors use their published full identifiers. Metadata checking
is reported as `catalog_checking`; it does not establish data qualification.

The sole `finalize_native_release` function requires accepted native evidence
and a passed DDK catalog bound to that exact candidate. It preflights the complete
control and manifest byte set before writes; identical retries keep file
custody, changed controls refuse, and missing identical controls can finish a
partial attempt. The managed caller captures original definitions and the first
accepted receipt, preserves native data paths, and finalizes controls before
requesting selection. Native execution owns recovery. The old `archive_schema`
generator is removed; its unchanged registry survives only as an independent
test oracle under `model/fixtures`. Retained application execution and complete
production adoption remain under acceptance.

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

Visitor descriptions added on 2026-11-06 explain each of the 23 maintained
datasets before its existing coverage limits and nullability explanation.
`Document details` and `Available materials for each meeting` are display titles;
their row meanings, identifiers and inclusion rules remain unchanged. Nested
field descriptions follow the physical declarations,
`docs/plans/phase-2-annex-20261028.md` §2–3,
`docs/engine-first-data-model.md` §8.1 and the corresponding `model/sql` owners
(`document-page-metadata.sql`, `entity-members.sql`, `entity-bills.sql`,
`entity-nominations.sql`, `entity-recordings.sql` and `retired-links.sql`).
Descriptions identify recorded values; they do not establish complete source
coverage, successful native execution or the correctness of observed values.

The additional `future_data` table belongs to the MCP reader test generator
`apps/explorer_mcp/tests/catalog_fixtures.py`, not this 23-dataset source. Its
standard declarations explicitly label its text and decimal values as synthetic.
A reader-fixture catalog therefore contains 24 datasets and remains a fixture.
Whether to publish that example outside a test capture remains a publisher
decision; this change neither publishes nor removes it.
