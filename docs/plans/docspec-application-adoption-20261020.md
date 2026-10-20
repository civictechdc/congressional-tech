# Congressional-tech adoption of DocSpec capabilities

Updated 20 October 2026. This is the application work plan under `ct-mi03`.
Engine upgrades are an upstream planning assumption. Current implementation
checks initially used clean DocSpec `9661026ca45712eb5c0e427cfd7896236bf8b3aa`, application
integration `34c1ee7a6d46258a3a362ff14cb4a11c0e071096`, and the separately
fingerprinted news code in the primary checkout. This review ran no tests or
provider operations and proves neither deployment nor production adoption.
A final source review covered native upgrades through clean
`22a804e19b8c8e376e28cf9612d4f8ae3b7b4726`; current capability statements below
include those changes. Their runtime qualification remains separate work.

The archive and news packages should use different native operations when their
work differs, through one configured client for transport, exact pins, errors,
streaming and input custody. Acquisition, document grouping, news evidence-union,
identity decisions, span merging, rights and publication policy stay in their
application owners. Do not replace sound domain code just to call another API.

## Work and dependencies

| Ticket | User result | Depends on |
|---|---|---|
| [ct-oxg6](../../.tickets/ct-oxg6.md) | One immutable, checked engine runtime | Existing host/custody fixes and ct-3li2/ct-cpio safety fixes |
| [ct-egpe](../../.tickets/ct-egpe.md) | Shared safe client for archive and news | ct-oxg6 |
| [ct-qkvr](../../.tickets/ct-qkvr.md) | Later news batches preserve earlier records | ct-egpe |
| [ct-nloa](../../.tickets/ct-nloa.md) | Small news updates avoid whole-table reads | ct-egpe |
| [ct-jo8n](../../.tickets/ct-jo8n.md) | Actual news callers read one complete published release | ct-qkvr, ct-nloa |
| [ct-gf8i](../../.tickets/ct-gf8i.md) | Typed spans and incrementally maintained news views | ct-jo8n |
| [ct-4nyy](../../.tickets/ct-4nyy.md) | Exact exports respect news rights and expiry | ct-jo8n |
| [ct-ugqq](../../.tickets/ct-ugqq.md) | Capture and publisher install the same qualified runtime | ct-egpe |
| [ct-ccy4](../../.tickets/ct-ccy4.md) | Measured spill/recovery stays within preparation disk budget | Existing preparation and capacity fixes |
| [ct-qdkd](../../.tickets/ct-qdkd.md) | Operators see progress, reusable work and resource costs | ct-egpe, ct-n7la |
| [ct-dmca](../../.tickets/ct-dmca.md) | Compatible fields and scalar enrichment evolve without full rewrites | ct-egpe |
| [ct-gziq](../../.tickets/ct-gziq.md) | Eligible catalog joins and rollups reuse unchanged results | ct-egpe |
| [ct-sb0s](../../.tickets/ct-sb0s.md) | Provenance/review evidence changes without rewriting source | ct-egpe |
| [ct-13cn](../../.tickets/ct-13cn.md) | Change reports and downstream work use exact native differences | ct-egpe |
| [ct-a70m](../../.tickets/ct-a70m.md) | Maintenance protects releases and recoverable operations | ct-qdkd |
| [ct-nc7l](../../.tickets/ct-nc7l.md) | Core archive integration is reviewed and tested locally | Runtime, client, preparation/spill, progress and accepted safety fixes |
| [ct-2ukk](../../.tickets/ct-2ukk.md) | Existing retained data is adopted and live behavior is verified | Existing adoption work, ct-nc7l, ct-ugqq |

News feature work does not block core archive qualification without an actual
shared dependency. No tickets were started by this planning pass. Local tests,
measured cost and independent review remain the implementation gates; no CI
dispatch, source acquisition, migration restart or production mutation occurred.

## Feature coverage and present limits

| Native feature family | Application use or decision |
|---|---|
| Build, Update and exact source reads | Already used by archive. Keep measured immutable Build for small archive leaves (ct-eipa). Correct news append semantics in ct-qkvr; use bounded merges in ct-nloa. |
| Owned host, deadlines, cancellation, streaming | Archive implementation exists; ct-egpe adopts it in news and removes duplicated transport/schema conversion. |
| Plans, completion reuse, inspection | ct-qdkd surfaces them; retries retain the original operation identity and source inputs. |
| Schema evolution and scalar/continuous backfill | ct-dmca. Continuous work and dependency correction apply only to supported row-local definitions, not arbitrary classification or graph changes. |
| Generations, input capture and dependency correction | ct-jo8n uses the relevant exact producer/input relationships. Application availability, cursors and release authority remain intact. |
| Joins and incremental aggregates | ct-gziq and ct-gf8i. Date32 and CountDistinct already have news consumers; no duplicate feature ticket. |
| Nested payloads and set-valued summaries | ct-gf8i. Root nested payloads can remove JSON transport; exact reader/refresh parity is required. CollectSet now supports sorted unique non-null lists in local Refresh; qualify the intended backend and corpus-wide membership semantics before adoption. |
| Occurrence evidence | ct-sb0s preserves receipt multiplicity, review ownership and source-document mappings. A locator is not a retained copy of the underlying evidence. |
| Compare and certified change streams | ct-13cn uses current `/compare` and `/changes`, preserving value versus occurrence semantics and metadata-only changes. |
| Explicit nested exports | ct-4nyy applies rights/expiry before native export. Native all-row/group export does not replace routed viewer assets or review bindings. |
| Retention, restore, compaction | ct-a70m binds protected releases and recovery prerequisites. Lifecycle compaction now has a local Rust API, without a CLI/HTTP route or remote support. Execute maintenance only when separately requested and justified by measurement; no automatic expiry or deletion. |
| Layout, partitioning, scoped reads and pruning | ct-qdkd/ct-a70m measure actual pressure; ct-nloa supplies a real selective-read need. Current public reads are whole-group; internal projection is not a scoped-read API. Small news tables start unpartitioned; I5 does not require MonthTransform. |
| Dagster, format upgrades, speculative indexes | No current application need established. Keep existing scheduling and supported format; do not add infrastructure for feature coverage. |

At the inspected engine head, R2 supports the source-focused Build/Update/read
profile and source comparisons. Schema/backfill, receipt updates, related refresh,
input capture, continuous backfill, dependency correction and compaction still
have local restrictions. Coupled generation sealing has no supported remote
producer path. Each application ticket must verify its intended backend before
activation; an exposed route is not sufficient. Public filtered/projected reads
remain absent. Partition-aware writers now support Identity, Day and Month
internally, but public write requests do not expose a layout choice and fresh
tables remain unpartitioned. Upstream changes remain outside these
application-only tickets and must not be silently reimplemented in Python.

The redundant dictionary settings for news column names found in the initial
review have been removed from both production writers by the final native
revision. Existing ct-cpio tracks that work and writer-budget safety; the chosen
runtime still needs qualification. News-shaped profiling fixtures are test-only
and can remain.

## Evidence and preservation

Fresh native and application source reviews, exact hashes and ticket mapping:
`output/docspec-reuse-20261020/adoption-review/` in the primary checkout.
The preparation report there retains the zero-spill outcome; ct-ccy4 covers the
remaining proof rather than treating a completed sort as evidence of spill.
Implementation must preserve ongoing primary news/UI edits, existing source
bytes, historical pins, source/document IDs, mappings and review decisions.
