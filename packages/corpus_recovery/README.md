# Corpus recovery

Python library that checks recovered committee documents and adds them to the raw archive.

Committee sites and the Library of Congress Web Harvest sometimes hold a hearing PDF or HTML page that the archive does not. This package is the code that turns a reviewed local copy into archive rows and, later, into a catalog update. Campaign commands are documented below; retained-package tools remain in [`scripts/corpus_recovery`](../../scripts/corpus_recovery/README.md).

```python
from corpus_recovery.reconcile import import_retained, reconcile
```

Import each operation from its owning module.

The package is installed with the rest of the workspace (`uv sync --locked`). Explicitly budgeted archive acquisition is available through `discovery_runtime`; the historical Web Harvest workflow remains in [`scripts/webharvest`](../../scripts/webharvest/README.md).

## What you can ask it to do

| Module | Role |
| --- | --- |
| `html` | Reads archived HTML and labels it: a real document body, an empty page, a "no prepared statement" page, or an error or challenge page. The caller still has to check the archive digest, the source URL, and any URL that was deliberately deferred. |
| `govinfo` | Validates a downloaded GovInfo ZIP and retains all members and its acquisition receipt, independently of the selected document's recovery mapping. |
| `inventory` | Loads a sealed batch, compares it with objects already stored, and checks that a file's digest still matches the manifest. |
| `reconcile` | Reconciles accepted recovery mappings against raw captures, stages provenance rows, and imports retained bodies through the common receipt writer. |
| `qualification` | Checks PDF decoding and all-page rendering, or classifies HTML, and retains results by verified bytes, validator implementation, reader tools, and limits. |

## Shared body qualification

Use `qualification.qualify(verify_local_file(path), cache_dir)` before accepting a
recovered body. The trusted `verify_local_file`, checked-copy, or owned-write
helpers establish byte integrity. Constructing `VerifiedFile` with an asserted
digest does not establish integrity. Cache hits check process-local file custody
before reopening body bytes; mutable files need verification after restart.

PDF qualification requires `pypdf>=6.19,<7`, `pdfinfo`, and `pdftoppm`. Install
Poppler with `brew install poppler` on macOS or `apt-get install poppler-utils`
on Linux. Every page must decode and render. Historical malformed text operands
may use a recorded fallback to decoded streams plus Poppler; decoder warnings,
corrupt streams, missing EOF, encryption, and incomplete rendering do not pass.
Readability does not establish the requested document's identity.

Completed results are immutable JSON files. Concurrent callers of the same cache
key share one worker through an advisory lock. Incomplete attempts, including
timeouts and missing tools, remain in `attempts/`; the next call retries them.
Callers own retry budgets and the lifetime of the cache and its tiny `.locks/`
files. `verify_qualification_record` checks serialized integrity and expected
bindings; a valid checksum alone does not make an untrusted result authoritative.

`QualificationConfig` defaults to a 16 MiB input ceiling, matching the measured
local acquisition limit. Larger explicit configurations need separate capacity
validation. It also bounds decoded content bytes, page count,
worker wall time, per-process CPU, and diagnostic file size. One worker runs at
most one Poppler child at a time; the caller owns aggregate concurrency. Linux
also enforces per-process address space. Both platforms sample process-tree RSS
and stop an observed excess. macOS has no enforced address-space limit here;
sampling cannot prove or prevent transient RSS peaks. Results report the sample
count, observed peak, elapsed time, and enforcement method. These checks do not
establish full-corpus or 16-worker capacity.

## What it will not do

It will not treat a download as success. A batch is usable only when the named files match the hashes recorded in its manifest.

Accepted recovery labels enter raw as provenance records and are consumed by the
archive model and publisher; the old catalog/viewer publication and shared-index
import dispatchers are retired.

## Campaign planning and accepted imports

`python -m corpus_recovery.campaign plan --campaign campaign.json --output plan --runtime runtime.json`
uses native metadata joins, with no acquisition or body-store scan. The version-1
campaign descriptor has `campaign_id`, one `requirement`, `tables` containing
`{path, sha256}` pins, and distinct `target_table`/`candidate_table` names.
Targets contain `target_url`; candidates contain `target_url,candidate_url`.
Literal URLs are the membership boundary. Duplicate or out-of-universe membership
cannot produce an admitted plan. Optional target fields are `subtype`,
`evidence_id`, `usable_direct`, `acquisition_excluded`, `unresolved_reason`,
`normalized_url`, `url_key`, `membership_origin` (`baseline`, `later_batch`, or
`unknown`; default `unknown`), and
`refresh_policy` (`historical_only` or `refresh_live`, defaulting to live refresh).
Direct-use and exclusion assertions require evidence IDs from the pinned inputs.

The planner writes `url-dispositions.parquet`, `recovery-requirements.parquet`,
`counts.json`, native queries, and `input-manifest.json`. All primary counts derive
from the ledger. It cannot infer a missing production baseline. To reuse published
eligibility, pin `state`, `state_profile`, and `state_requirements`; the profile
must bind those requirements and the current acceptance policy. Satisfaction for
a different target requirement does not transfer to the new campaign.

`python -m corpus_recovery.campaign import --campaign campaign.json --request request.json
--output operation --runtime runtime.json --local-store raw --writer-identity writer.json`
qualifies one pinned body, establishes identity, and uses the existing retained
import and provenance writers. The request contains:

- `body` and `receipt`: exact `{path, sha256}` pins. The receipt must bind the
  complete successful capture, literal candidate URL, byte count, digest and time.
- `target` and `candidate`: identity-source descriptions containing a pinned
  `source` JSON file, `source_url`, `record_pointer`, `url_field`,
  `identifier_fields` mapping native facts to record fields, and `required_fields`.
  Supply a source-capture `receipt` pin, or explicit `reviewed_by` and `reviewed_at`
  for retained metadata. A filename or an unreferenced assertion is insufficient.
- `relationship`, `decided_by`, `decided_at`, and optional `supersedes`.

An updated revision with changed version/date/title requires `current_official_counterpart`
and a `relationship_field` extracted from the candidate's pinned source record.
That field must explicitly name the relationship, exact `target_url`, and all
`target_identifiers`; native lineage and other context must still agree. A missing
bridge remains unresolved. Body readability alone never establishes identity.

The operation freezes input identity and uses stable receipt/provenance keys.
Rerun the same request and output to continue. Changed inputs require a new
operation. Qualification and identity evidence remain with the operation.
Version-2 provenance is a trusted producer attestation; the native model verifies
its typed inputs and retained-body match, while this producer proves the referenced
qualification and identity evidence. Generic provenance writers remain trusted
administrative entry points.

## Bounded archive and search discovery

`python -m corpus_recovery.discovery_runtime --campaign campaign.json --target URL
--source wayback --work discovery --runtime runtime.json --max-pages 2
--request-cap 10 --spend-cap-micros 100 --admission-db campaign-admission.sqlite`
queries only an admitted target. Web Harvest additionally takes
`--source webharvest --collection congress118th`. Use the **same admission database
and caps** for capture (`congress_api.cli.capture_schedule --admission-db ...`) and
discovery. The database persists reservations, including uncertain outcomes. Keep campaign
work directories and the shared database outside the clean writer checkout, as
the capture CLI requires.
The work directory freezes response evidence; use a new explicitly chosen work
scope for a later discovery observation rather than treating a cached negative as
permanent absence.

`DiscoveryRuntime.replay` returns a durable sealed `FetchResult`; it validates
archive host, original URL, timestamp, replay mode, final URL and available digest.
It does not materialize a PDF in memory. Campaign consumers must pin discovered
candidate membership before acquisition/import. Discovery does not authorize
identity acceptance. `DiscoveryRuntime.search` provides a scoped, budgeted
Firecrawl search callback to `relocated_search`, retains response evidence, and
reports results as non-exhaustive leads. No scrape is requested by search.
The adapter follows the [official Firecrawl search response](https://github.com/firecrawl/firecrawl-docs/blob/main/features/search.mdx).
Caller-supplied positive price bounds are reservations, not current-price claims.
Local tests use recorded responses; live archive/provider acceptance remains a
separate operational check.
