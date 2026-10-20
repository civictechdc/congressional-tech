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
