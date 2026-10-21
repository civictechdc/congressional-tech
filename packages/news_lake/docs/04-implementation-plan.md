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
