# Published Congress data: keys and relationships

The current archive code uses one standard DDK catalog. Production cutover is
still under [acceptance](replacement-ddk/status.json). Dataset meaning, fields,
nullability and coverage limits are authored in
[`archive.odcs.json`](../model/ddk/archive.odcs.json). Product descriptions live in
[`archive.odps.json`](../model/ddk/archive.odps.json). Identities, relationships
and recipes live in [`project.ddk.json`](../model/ddk/project.ddk.json), with
recipe SQL under [`queries/`](../model/ddk/queries/). The maintained DDK assembler
checks these sources and emits the catalog and exact companions.

Consumers read `catalog.ddk.json`, `catalog.report.json` and `catalog.lock.json`
from the selected immutable release. They resolve a recipe's content-addressed
SQL companion from that same file inventory. Discovery reports definitions and
observed coverage; it does not execute SQL, fetch external targets, or claim that
metadata checking proves data correctness.

- A physical key identifies a record within its declared scope. Binary hashes
  retain their published byte types; hexadecimal is a display encoding.
- `list_row` identifies a zero-based row position within one release, including
  shard offsets. It is not an identifier across releases.
- Typed relationship paths distinguish fields from list elements. Cardinality
  applies across the declared source and target rows, including their elements.
- A missing table is unavailable. A present empty table has zero rows. A null
  value remains unknown or absent. Bounded coverage can leave optional references
  unresolved without asserting that an external record does not exist.
- Recipes declare their SQL dialect, input tables, positional `parameterOrder`
  and result grain. Contextual relationships explain the recipe; they do not add
  table reads. Unnest only the lists needed by a query, and preserve document
  grain when counting across several relationships.

The [catalog guide](../model/ddk/README.md) describes disclosure and checking.
The [data model](engine-first-data-model.md#84-standard-catalog-and-native-qualification)
explains the native qualification boundary. [Release notes](releases/README.md)
record published identifier and behavior changes. The complete migration's
implementation and acceptance state remains in
[replacement status](replacement-ddk/status.json).

There is no separate schema generator or `schema.json` reader. The frozen
pre-migration registry under `model/fixtures` is an independent test oracle,
never a producer or consumer input.
