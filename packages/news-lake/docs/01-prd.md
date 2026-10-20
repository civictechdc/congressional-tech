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
