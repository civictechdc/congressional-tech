# Political News Lake — v0.1 packet
**Parquet + Apache Iceberg · Independent Editor’s Draft · 20 October 2026**

| Read in order | Purpose |
|---|---|
| [01 — PRD](01-prd.md) | Outcome, scope and selected upstream concepts |
| [02 — Core specification](02-core-spec.md) | Record grains, identity, evidence and conformance |
| [03 — Iceberg profile](03-iceberg-profile.md) | Types, replay, commits, releases and evolution |
| [JSON Schema](schema/news-lake.schema.json) | Closed Draft 2020-12 record contract; 13 record kinds |
| [04 — Implementation plan](04-implementation-plan.md) | Six bounded slices and acceptance gates |

[Single reading copy](packet.md) combines the prose documents; the JSON Schema remains separate to avoid duplicating its authority. [Synthetic records](examples/records.jsonl) exercise every kind. Run `python checks/validate.py` with `jsonschema` installed (tested with 4.26.0). Its scope is local validation, not a lake deployment.

**Scope:** Articles and political entities first. Events, embeddings, notifications and UI are intentionally deferred. Reusable records—not a merger of five application databases. Specifications are proposed project contracts, not upstream behavior guarantees or W3C publications.

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
