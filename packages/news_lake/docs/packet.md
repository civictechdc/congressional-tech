# Political News Lake — Design Packet

**v0.1.0 · 20 October 2026 · Parquet + Iceberg**

# Political News Lake — PRD
**Proposed · v0.1.0 · 20 October 2026**

## Outcome and scope
A reusable politician-aware corpus in **Parquet + Apache Iceberg**: backfill available history, acquire hourly, and query who appeared in which publications with inspectable evidence. Collect each article once; associate it with many people.

| Requirement | Acceptance |
|---|---|
| P1. Coverage | RSS, Media Cloud and GDELT use one record contract; provider gaps/failures remain visible. |
| P2. History | Distinguish sightings, publication appearances and extracted versions; replay creates no duplicate logical records. |
| P3. Identity | Preserve stable IDs, crosswalks, dated offices, unresolved names and mention spans. |
| P4. Analysis | Filter by person/date/outlet/aboutness; count articles separately from stories and identical-text groups. |
| P5. Operations | Hourly acquisition; publish a completed pilot batch before the next cycle. Measure discovery-to-release separately from publication-to-discovery latency. |

**Pilot:** Five politicians, a manually audited 30-day sample, then available backfill. Report precision, provider overlap, unique additions, extraction success and latency. Neither “every article” nor a complete historical archive is promised.

## Model influences
| Source | Adopt |
|---|---|
| Media Cloud [MC] | Capture/content separation; publisher/feed provenance |
| NewsIntel [NI] | Versioned NLP; observed names; reversible authority; story membership |
| OPOL [OP] | Many-to-many entities; typed, attributed classifications |
| Avanguardia Publica [AV] | External-ID crosswalks; conflicts held for review |
| Open Aggregator [OA] | Separate outlet appearances; explicit undated coverage |

These are design influences, not upstream compatibility guarantees. Keep small aliases/identifiers/tenures nested; keep growing evidence separate.

**Deferred:** Dashboards, notifications, embeddings, broadcast ingestion, long-running event graphs and universal taxonomies. Do not merge the upstream applications or inherit their rankings, retention policies and schedulers. Metadata-only articles remain valid. References: [README](README.md).


---

# Political News Lake 0.1 — Core Data Model
**Independent Editor’s Draft · v0.1.0 · 20 October 2026**

## Abstract and status
An interoperable evidence-backed news model, independent of processing frameworks. This is **not a W3C standard or submission**. Uppercase requirement terms follow BCP 14 [BCP14]. Sections 1–4 are normative; examples and PRD are informative.

**Conformance:** Record Producers satisfy the JSON Schema and C1–C6. Corpus Publishers also enforce C7–C9 and the Iceberg Profile. Consumers honor pinned releases, access restrictions and analytical selections. JSON validity alone is insufficient.

## 1. Records
One JSONL object per record, validated against `schema/news-lake.schema.json` (Draft 2020-12). All have `kind`, lowercase UUID `id` and UTC `recorded_at`. Optional absent fields mean unknown/not supplied; JSON null is forbidden. Empty arrays describe recorded entries, not universal absence.

| Kind → table | Grain |
|---|---|
| `outlet` → `outlets` | Publication brand, domains and feeds; not the discovery provider |
| `capture` → `captures` | Response/fetch attempt, outcome and retention policy |
| `discovery` → `discoveries` | Captured provider result linked to one item |
| `item` → `items` | Publication appearance, URL aliases and selected version |
| `version` → `versions` | Immutable extraction result; text optional |
| `entity` → `entities` | Person/organization/place; aliases, crosswalks, dated tenures |
| `identity_decision` → `identity_decisions` | Equivalence, distinction or retraction |
| `run` → `runs` | Completed processing attempt, inputs/configuration/outcome |
| `mention` → `mentions` | Surface form and spans within a version, per linking run |
| `classification` → `classifications` | Typed value per version/dimension/optional target/run |
| `story` → `stories` | Cluster within one clustering run |
| `story_member` → `story_members` | Version-to-story assignment within that run |
| `release` → `releases` | Validated snapshot set, processor selections and checkpoints |

All tables use `news`. Provider/query identifiers refer to versioned adapter configuration, retained with source checkpoints; separate provider/event/collection tables are not required.

## 2. Publication and evidence
**C1 — Identity.** IDs MUST survive replay. Title, politician name and text hash MUST NOT identify articles. Preserve original URLs and aliases. Redirect evidence may consolidate one publisher’s URLs; a cross-domain canonical tag alone MUST NOT collapse another outlet’s appearance. Reconciled duplicates retain acyclic `superseded_by` links; old references resolve to the survivor.

**C2 — Observations.** Different providers finding one item create different discoveries. Replaying one captured result reuses its ID; a new successful poll is a new observation. Search hits are not confirmed entity mentions. Captures MUST distinguish `succeeded`, `not_modified` and `failed`; failures retain an `error_code`. Credentials MUST be redacted from URLs and checkpoints.

**C3 — Time.** Acquisition/first-seen timestamps MUST NOT substitute for publication time. Publication is `unknown`, `day` with a date, or `instant` with a UTC timestamp; known values retain publisher/provider basis. Never invent midnight. Tenures use inclusive `from`, exclusive `to`; missing endpoints mean unknown, not verified current service.

**C4 — Versions.** Versions/runs are immutable. Changed extraction inputs/configuration create new results, not automatically publisher edits. `text_hash` MUST equal SHA-256 of exact stored UTF-8 text. `input_hash` covers actual ordered inputs under documented normalization; `config_hash` includes settings and model version. No-title discoveries may remain items without a version; titles MUST NOT be fabricated.

**C5 — Access.** `metadata_only` omits bodies. Retained payload/text requires an explicit `rights_basis`; `restricted` is not a redistribution grant. Exporters MUST omit unauthorized bodies. Expiry/deletion policy reaches raw objects, derived text, indexes and retained snapshots; metadata retention is also policy-dependent. Public metadata projections are not canonical re-import records.

## 3. Intelligence
**C6 — Entity evidence.** Resolved mentions require an entity ID; unresolved/ambiguous mentions forbid one. Names alone MUST NOT merge entities. Preserve dated office/affiliation history. `same_as(left,right)` maps left to right; `different_from` prohibits equivalence; `retract` names a prior decision. Apply unretracted decisions in `(recorded_at,id)` order; reject cycles, contradictory mappings and authoritative-ID conflicts. Retractions MUST target an earlier non-retraction. Preserve original mentions and decisions.

Spans MUST be nonempty, in bounds and equal `surface`: zero-based Unicode code-point offsets, exclusive end, into exact version `title`/`text`. Aboutness differs from identity confidence. Scores are method-specific, not presumed calibrated probabilities. Classifications require dimension, taxonomy version, run and exactly one typed value. Person-targeted sentiment identifies its target. Syndicated appearances remain separate items; clusters do not prove independent reporting or permanent event identity.

## 4. Corpus rules
**C7 — Integrity.** Publishers MUST enforce unique IDs/references, valid intervals/hashes/spans and successful output runs with matching inputs. Immutable-ID collisions with different values fail. Current versions belong to their items; story/member runs agree; each version belongs to at most one story per clustering run. Input references are acyclic. The schema cannot enforce these cross-record rules.

**C8 — Selection.** Releases pin processor/version/configuration triples. For each input/processor, select the latest successful matching run by `(finished_at,id)`; zero-output success replaces older results. `current_version_id` explicitly selects text. Unprocessed inputs stay visibly pending. Reprocessing preserves history and MUST NOT become new-discovery coverage.

**C9 — Views.** `politician_articles` has at most one row per resolved person-root/current item/release, retaining version/run IDs and aboutness. Union duplicate spans across aliases. `coverage_daily` counts distinct items/outlets/stories; unknown publication dates form an undated group. Identical-text counts MUST NOT be labeled independent-reporting counts. Derived tables record their source release.

Schema governs shape; this text governs semantics. Validators MUST check UUID/URI/date/date-time formats [JSON] and reject non-finite numbers. The included checker covers selected local invariants, not full conformance.


---

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


---

# JSON Schema

[The normative JSON Schema](schema/news-lake.schema.json) defines all 13 record kinds. [Synthetic fixtures](examples/records.jsonl) and [the local checker](checks/validate.py) accompany it. Shape validation is separate from corpus and persistence conformance.

---

# Political News Lake — Implementation Plan

| Slice | Deliverable | Exit gate |
|---|---|---|
| 1. Contract | Freeze schema; implement semantic checks; pin reused code/dependencies. | Positive/negative fixtures, actual baseline and C1–C9. |
| 2. Lake boundary | Catalog, field-ID migrations, commit coordinator, replay keys, releases. | Replay twice; crash after each commit; old release remains readable; recovery converges. I1–I4. |
| 3. RSS | Capture → discovery/item → extraction; established parser/extractor. | Redirects, duplicate URLs, unknown dates, blocked fetch and metadata-only access. C1–C5. |
| 4. Identity | Five authoritative people; aliases/tenures; spans; reversible decisions. | Same-name people, rename, conflicts, merge/retract and stale offsets. C6–C8. |
| 5. Other sources | Media Cloud/GDELT adapters, paginated backfills and overlapping hourly windows. | Late arrivals, quotas, provider overlap and replayed pages; no incomplete cursor advancement. P1/P5. |
| 6. Analysis | One clusterer, typed labels and release-scoped views. | Syndication counts, changed models, zero-output runs and undated coverage. C8–C9. |

**Implementation:** Python, an existing schema validator, Arrow-compatible batches, and a supported Iceberg writer/catalog. Pin and test timestamp/nested-type round trips before deployment. Keep adapters, identity, enrichment and storage distinct; shared rules have one owner. Check source revision/license before code reuse. No combined upstream stacks, plugin framework or duplicate scheduler.

Retain prior cases as regressions after each slice; distinguish preparatory refactoring from behavior changes. Add restricted-export, retired-snapshot, Unicode-offset, schema-evolution and concurrent-acquisition tests. Report environmental failures separately. These are engineering gates, not a claimed measured effect of the supplied skill.

**Delivered here:** Draft contracts, schema, synthetic fixtures and an offline checker; actual results are in `checks/validation-report.txt`. The offline lake boundary and the adapter/identity/analysis cores landed in [`packages/news_lake`](../../packages/news_lake/README.md) (see `docs/adr/news-lake-contract.md`).

**Still to implement:** Live integrations, access/retention enforcement on export and measured coverage/throughput. The typed-label producer, the pilot's five-politician roster and the audited 30-day coverage/latency report remain; scale according to measured gaps.


---

## References
[BCP14] [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119.html) and [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174.html). Normative keyword semantics.

[JSON] [JSON Schema 2020-12 Validation](https://json-schema.org/draft/2020-12/json-schema-validation). Structural validation and explicit format checking.

[ICE] [Apache Iceberg specification](https://iceberg.apache.org/spec/), format-v2 sections, Identifier Field IDs, Optimistic Concurrency, Parquet mappings and Partition Evolution. The project deliberately targets v2, not every feature in the current specification.

[MC] [Media Cloud story model](https://github.com/mediacloud/story-indexer/blob/main/indexer/story.py).
[NI] [NewsIntel annotations](https://github.com/itheCreator1/newsintel/blob/main/backend/app/nlp/models.py) and [entity authority](https://github.com/itheCreator1/newsintel/blob/main/backend/app/entities/models.py).
[OP] [OPOL content/classification model](https://github.com/open-politics/opol/blob/main/opol/stack/core/models.py).
[AV] [Avanguardia identity types](https://github.com/ZDOSS/Avanguardia-Publica/blob/main/scraper/identity/types.py).
[OA] [Open Aggregator coverage types](https://github.com/jwmeyert7/open-aggregator/blob/main/src/lib/types.ts).

Repository references trace concepts inspected in the preceding design discussion; they are not pinned dependencies and no upstream code is included. Implementation must pin and recheck exact revisions. External standards were checked for this packet; neither upstream maturity nor production behavior was retested.

Supplied engineering notes: `SKILL(2).md` (bounded change and behavioral evidence), `scenarios.md` (proposed multi-checkpoint evaluation), `evidence.md` (synthesis versus measured findings). They inform delivery gates only, not the news model or claims of demonstrated effectiveness.
