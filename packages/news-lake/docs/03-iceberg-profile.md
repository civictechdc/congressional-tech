# Political News Lake 0.1 — Iceberg Profile
**Independent Editor’s Draft · v0.1.0 · 20 October 2026**

## Abstract and status
Parquet-backed storage and a consistent publication boundary for the Core Model. Not a W3C publication. I1–I6 are normative; tuning guidance is informative. BCP 14 applies.

## 1. Representation
**I1 — Mapping.** Writers MUST use Iceberg **format v2**, Parquet data files and catalog-managed commits. `x-iceberg.table` specifies routing; record properties become columns except `kind`. Preserve raw bytes as external capture objects, not arbitrary JSON columns.

| JSON | Iceberg |
|---|---|
| UUID/hash/URL/string/enum | `string` |
| date-time / date | `timestamptz` (microseconds) / `date` |
| integer / finite number / boolean | `long` / `double` / `boolean` |
| object / homogeneous array | `struct` / `list` with non-null elements |

Required fields become required columns; missing optional fields become SQL NULL and are omitted on JSON export. Conditional requirements remain validator checks. Snapshot IDs are digit strings parsed as positive signed 64-bit integers. Persist field IDs, including nested/list-element IDs, in migrations; never reuse or regenerate them from column order [ICE].

## 2. Commit and release
**I2 — Replay.** `outlets`, `items`, `entities` upsert by ID; other tables append immutable logical evidence, except policy deletion. Both modes MUST deduplicate replayed IDs. Iceberg does not enforce uniqueness [ICE]. Use one fenced commit coordinator; concurrent acquisition is allowed. Stage durable checkpoints after record commits, but advance the active cursor only after release publication. Crash recovery MUST reuse IDs and converge. Do not claim exactly-once transport.

**I3 — Publish last.** Commit candidate tables, validate C7 against their exact snapshots, stage checkpoints, then append the release. These are not automatically a cross-table transaction. Interrupted work leaves the prior release usable.

A release MUST name exactly the twelve non-release tables with their table UUIDs; absent `snapshot_id` means explicitly empty, never “latest.” Select at most one configuration per processor. Consumers MUST use pinned snapshots and reject missing snapshots or UUID mismatches.

**I4 — Retention.** Protect snapshots referenced by supported releases. Before expiry/policy deletion, retire affected releases in the control-plane availability registry; consumers reject retired releases. Deletion must include raw objects, derived copies, snapshot expiration and orphan cleanup. Iceberg time travel is not permanent application history [ICE].

## 3. Layout and evolution
**I5 — Layout.** Start small tables unpartitioned. At measured volume, use date transforms such as `day(observed_at)` or `day(recorded_at)`. Do not partition articles by politician or create one file per politician/hour. Compaction/evolution MUST preserve logical results and supported releases [ICE]. An initial 128–512 MiB file target is tuning guidance, not conformance.

**I6 — Evolution.** Every release declares its contract version. Optional additions may be compatible; changed meanings, required fields or closed enums need an explicit contract migration. Readers use the matching schema. Preserve field IDs and test round trips. No particular catalog vendor or compute engine is required.

Operational leases/retries/cursors belong in a small transactional control store; evidence belongs in Iceberg. Search/UI remain rebuildable consumers.
