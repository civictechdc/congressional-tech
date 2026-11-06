# Non-archive workflow definitions

These definitions let the maintained Data Design Kit (DDK) assemble a catalog
and check the declared interfaces for news, YouTube, Committee Explorer
compatibility exports, and inflation/Sheets. They describe 4 products and 28
semantic datasets using Open Data Contract Standard (ODCS) 3.2.0 and Open Data
Product Standard (ODPS) 1.1.0. They do not replace those workflows' execution.

`project.ddk.json` imports the four projects. Components describe the owning
domain operations, parameters, inputs and outputs. Designs exercise selected
interfaces; they are not complete execution plans. Every component has
`executionStatus: interface_only` and `runtimeBinding: unqualified`, and none
selects an implementation. Products remain draft and declare no server,
distribution, successful source contact, or observed release.

## Authority and supported scope

| Workflow | What the standard definitions describe | Incoming validation owner | Exact stored output owner |
| --- | --- | --- | --- |
| News | Supplied fetch outcomes, all 13 retained record kinds, two release views, provider interpretation and publication interfaces | `news_lake.adapters.common.FetchOutcome`, `news_lake.contract.records.validate_shape` and the maintained `news-lake.schema.json` | That schema's `x-iceberg` annotations, `news_lake.storage.docspec.schema.kind_arrow_schema`, and the pinned native runtime |
| YouTube | Channel/video cache identity, distinct playlist/video timestamps, and scoped caption-index outcomes | `youtube_api.models.SourceModel` and the provider-specific models | Maintained TinyDB/SDK/yt-dlp cache and caption files; no native table representation is qualified here |
| Committee compatibility | Five browse tables, source rows, complete publication manifest, and Parquet-only export | `committee_meeting.catalog.Catalog` validates the complete graph; `PublicationManifest` validates publication inputs and scope | `committee_explorer.parquet.TABLE_SCHEMAS` and `SOURCE_SCHEMA`; output partitions are not complete input graphs |
| Inflation/Sheets | Year/month CPI index grid, monthly year-over-year percentage columns, optional derived aggregate | Maintained BLS/FRED/manual adapters and scripts | Maintained CSV scripts own actual columns, revisions and serialization; required-source/freshness policy is unresolved |

ODCS `authoritativeDefinitions` links point to these existing owners. The
released DDK core does not execute or validate the Python symbols behind links
of type `implementation`. The focused tests check that the linked files exist
and compare the declared scalar subset with selected actual owner schemas.
This is a source binding, not proof of exact physical mapping. No physical
types, field IDs, native schemas, schema converter or runtime serializer is
authored in this directory.

The reusable scalar profile here is string, integer, number, boolean, date and
timestamp. Exact nested structures, unions, alias/extras handling, field IDs,
CSV missing cells and conditional requirements remain with their current
owners. Any later shared binding must preserve the following examples rather
than silently reducing them to scalar compatibility:

* News: `publication` has unknown/day/instant alternatives; captures conditionally
  forbid payload fields for metadata-only access and require payload/rights
  evidence for retained access. Explicit JSON nulls and non-finite values are
  refused before shape validation. Native Arrow nullability alone does not
  express these rules. See
  `packages/news_lake/src/news_lake/contract/records.py:20-63`,
  `packages/news_lake/src/news_lake/adapters/common.py:60-99`, and
  `packages/news_lake/src/news_lake/storage/docspec/schema.py:181-211`.
* Committee compatibility: the exact outputs include lists of links/notes and
  an evidence-state struct. The input `Catalog` also checks cross-record
  identities/references, and a publication has nonempty input snapshots and
  typed included/partial/not-collected/not-supported/failed/unknown source
  scopes. Scalar ID compatibility cannot establish those properties. See
  `apps/committee_youtube/src/committee_explorer/parquet.py:154-212`,
  `packages/committee_meeting/src/committee_meeting/catalog.py:58-146`, and
  `packages/committee_meeting/src/committee_meeting/publication.py:45-93`.
* YouTube: incoming models allow unknown publisher fields and preserve original
  alias presence. `publishedAt` is playlist addition; `videoPublishedAt` is video
  publication. Missing/false caption flags do not establish absent automatic
  captions. An API flag does not establish retained caption bytes or language.
  See `packages/youtube_api/src/youtube_api/models.py:7-23` and
  `packages/youtube_api/src/youtube_api/interpretation.py:1-92`.
* Inflation: the historical grid stores index levels, whereas combined columns
  store year-over-year percentages. Missing months are empty, and optional
  sources may omit whole columns. With no successful sources the current
  script leaves the previous CSV and exits zero. With partial success it writes
  only returned columns; previous omitted columns are not carried forward.
  See `apps/inflation_gsheets/src/sources/bls.py:20-65` and
  `apps/inflation_gsheets/src/fetch-inflation-sources.py:124-180`.

RSS, GDELT and Media Cloud adapters consume supplied outcomes; these definitions
do not establish a live article-fetch service or verify caller-supplied payload
URIs. Failed, metadata-only and not-modified captures remain distinct. YouTube
caption failure remains unknown rather than a successful no-English-track
result. Compatibility JSON export remains retired. Adobe and PriceStats remain
manual inputs, without invented live feeds. CPI policy commentary and current
all-source-failure behavior still need a maintainer decision before replacement
acceptance.

## Source census and limits

`source-entrypoints.json` records a bounded syntactic census of 863 source files
(6,410,969 bytes), with limits of 1,500 files and 16 MiB. It excludes tests,
environments, vendored code and payload corpora. It enumerates 21 console-script
declarations plus recognized Python main guards, shell/Sheets/Rust entrypoints
and explicit read/fetch call sites. Every listed entry has an owning area and
an unverified replacement status. Generic `fetch`/session calls can include
local reads; dynamically constructed calls can escape this syntax inventory.

Source bodies, rather than command names alone, establish these additional
boundaries alongside the detailed acquisition inventory:

| Maintained entrypoint/body | Observed boundary |
| --- | --- |
| `packages/congress_api/src/congress_api/cli/fetch_meetings.py:1-215` | Raw fetch preview/apply paths, local spool and raw-store writes. GPO collection and Senate page defaults remain outside the committed daily prefix list; this census does not close that discovery gap. |
| `packages/congress_api/src/congress_api/cli/probe_house_sites.py` | Bounded HTTP probes retain request/body/failure evidence; they do not update collection state or import raw captures. |
| `scripts/measure/fetch_public_bodies.py` | Named retained-body restoration verifies newly fetched bytes before rename. Existing files are reused by existence and are not rehashed on that path. |
| `scripts/webharvest/webharvest_index_remaining.py:234-299` | Bounded CDX index metadata and retry/resume evidence; index success does not establish replay-body availability. |
| `scripts/webharvest/webharvest_committee_map.py:104-160` | Retained collection-page identity/status checks and committee mapping; not a complete upstream-site population. |
| `scripts/webharvest/webharvest_committee_map.py:223-307` | Separate bounded homepage/header probes; not document availability evidence. |
| `scripts/webharvest/webharvest_recovery.py:193-294` | Exact replay URL/provider and identity rules distinguish raw bytes from rendered copies. Plan/acquire/qualify operators do not import or publish. |
| `scripts/corpus_recovery/prepare_corpus_recovery_batch.py:1-105` | Seals a new local recovery batch from retained evidence; publication remains a separate guarded operation. |
| `scripts/corpus_recovery/prepare_corpus_recovery_source_records.py:1-135` | Requires exact transport/raw-source identity evidence; refuses unsupported rendered-source claims and implicit output reuse. |
| `packages/corpus_recovery/src/corpus_recovery/discovery.py:387-430` | The module CLI consumes an offline JSON fixture; reusable acquisition routines use an injected bounded call function. |

This closes recognized declarations for the recorded source path set. It does
not establish upstream completeness, enablement of every schedule, every
dynamic network effect, source access, retained-original coverage or execution
acceptance. No entrypoint was invoked and no new source contacts were made for
the census. The retained audit boundaries and unresolved capabilities remain
in `docs/replacement-ddk/acquisition-lifecycle.md` and
`acquisition-capabilities.json`; samples are not corpus coverage.

## Checks and next integration

Use the installed maintained APIs directly:

```python
from pathlib import Path
from ddk.core import check_project
from ddk.catalog import build_catalog

root = Path.cwd()
project = root / "model/ddk-workflows/project.ddk.json"
checks = check_project(project, permitted_roots=[root])
catalog = build_catalog(project, permitted_roots=[root])
```

The qualified DDK `0.1.0.dev4` admits the standards documents and declared graph.
All eight focused definition tests passed. Its catalog
contains 4 products, 28 datasets and 14 declared productions, with zero observed
versions, representations, releases, selections or runs. The focused source
test module is
`packages/congress_api/tests/test_ddk_workflow_definitions.py`. It includes a
poisoned `format=json` call to prove that a supported/retired parameter mismatch
fails the maintained call check. Those checks do not execute a collector,
native storage engine, export or publication, and do not qualify workflow
replacement.

The immediate simplification is one standard catalog assembly for these
products and ports, replacing future hand-maintained consumer lists. Connect
that catalog through the shared maintained catalog API before retiring any
consumer list. Keep domain merge, refusal, graph and source-evidence checks in
their existing owners. A shared native binding can later reference the news
and compatibility physical owners without another authored schema. YouTube
needs an admitted non-native representation before an execution binding. CPI
needs an explicit partial/freshness policy before source-column behavior can
move. No source executor, schema authority or domain validation is retired by
this increment.
