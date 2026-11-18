# Corpus recovery

Python library that checks recovered committee documents and adds them to the raw archive.

Committee sites and the National Archives Congressional Web Harvest sometimes hold a hearing PDF or HTML page that the archive does not. This package is the code that turns a reviewed local copy into archive rows and, later, into a catalog update. Campaign commands are documented below; retained-package tools remain in [`scripts/corpus_recovery`](../../scripts/corpus_recovery/README.md).

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
the Poppler release pinned in the root `test-suites.toml` (see
[development](../../docs/development.md)). Every page must decode and render. Historical malformed text operands
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
- Optional `match_basis`: `official_document_identifier` (the legacy default),
  or `source_catalog_document_identifier` when a source catalog issues the
  identifier. The request pins the choice; it does not change identity admission.
  Keep the actual catalog and reviewer in the pinned identity-source evidence.

An updated revision with changed version/date/title requires `current_official_counterpart`
and a `relationship_field` extracted from the candidate's pinned source record.
That field must explicitly name the relationship, exact `target_url`, and all
`target_identifiers`; native lineage and other context must still agree. A missing
bridge remains unresolved. Body readability alone never establishes identity.

The operation freezes input identity and uses stable receipt/provenance keys.
Rerun the same request and output to continue. Changed inputs require a new
operation. A validated accepted acknowledgement replays its original decision
and keys without reopening body/source files, repeating qualification or
reauthoring provenance. Later explanation-authoring changes therefore cannot
rewrite the acknowledged operation. Corrupt acknowledgement/evidence refuses.
Qualification and identity evidence remain with the operation.

The operation retains the exact request bytes for metadata-only replay and
reporting. Both consumers use one validator: every decision field must match
the pinned request/evidence and selected note policy, the receipt key must match
the frozen receipt metadata/content, and the provenance key must match the
original timestamp and operation ID. Older operations without a request snapshot
can be reported with `progress --request ORIGINAL_REQUEST` (repeatable); its
digest must match the original binding. Reporting leaves those operations
unchanged. A same-binding retry can retain the missing request snapshot without
reading bodies or source records. Missing/corrupt retained metadata refuses;
another supplied request cannot hide a corrupt existing snapshot.
Version-2 provenance is a trusted producer attestation; the native model verifies
its typed inputs and retained-body match, while this producer proves the referenced
qualification and identity evidence. Generic provenance writers remain trusted
administrative entry points.

### Resume and report one execution

`pipeline.run_recovery_campaign` prepares a new execution. Its `counts` and
`initial_counts` describe the **initial** plan, including when imports follow.
It refuses an existing `campaign.json` before inventory or discovery can replace
the inputs. Use `pipeline.resume_recovery_campaign(original_descriptor, ...)`
with the original request files to continue. It reuses the initial plan and the
same digest-named import operations; it performs no discovery or acquisition.

After the model owner selects updated state, write a **separate** final descriptor
with the same campaign ID, requirement, target and candidate pins. Only its
`state`, `state_profile` and `state_requirements` pins may change. The maintained
model must produce the version-2 profile and explicit eligibility fields. A
descriptor prepared for initial planning alone does not authorize campaign capture.

```sh
python -m corpus_recovery.progress --campaign original/campaign.json \
  --operation original/operations/import-REQUEST_DIGEST \
  --final-campaign final/campaign.json --output final/report \
  --runtime runtime.json --release-comparison release-comparison.json
```

Omit `--final-campaign` and `--release-comparison` for an initial/import-only
report. Supply every operation directory being assessed, including interrupted
ones; omitted operations remain unassessed. Each result must bind the original
descriptor and request digests. The native join writes `target-progress.parquet`
and `progress.json`, keeping the original ledger, final ledger, operation IDs,
candidate addresses, body hashes, receipt keys and provenance keys separate.
Interrupted operations without target evidence stay explicitly unmapped.

The existing release comparison must name both releases and include the original
descriptor through `--record-digest original/campaign.json`. Its release-wide
result does not establish a cohort attachment or a semantic-document gain.
Those counts remain null until the release owner verifies selected input
membership and exact target/body attachment through the reader and MCP. Keep
accepted targets, distinct bodies, target/body relationships, imports,
occurrences and document rows in their own units. Use a new report directory for
each later state observation; never import using the final report's descriptor.

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
identity acceptance. `DiscoveryRuntime.search` (paid, scoped to the allowed
hosts) and `DiscoveryRuntime.gov_search` (free) are search callbacks for
`relocated_search`; both retain response evidence, share the request cap, and
report results as non-exhaustive leads. No scrape is requested by search.
The adapter follows the [official Firecrawl search response](https://github.com/firecrawl/firecrawl-docs/blob/main/features/search.mdx).
Caller-supplied positive price bounds are reservations, not current-price claims.
Local tests use recorded responses; live archive/provider acceptance remains a
separate operational check.

### Recovery ladder

After a clean 404/410, or a body that fails qualification, try these rungs in
order. Each yields leads only; a lead counts after acquisition, qualification
(every PDF page renders) and identity acceptance from source-native records.

1. Web Harvest: the exact address (`campaign_lookup`), then the file name on the
   publisher's site (`webharvest_name_lookup`).
2. Wayback (`wayback_lookup`).
3. Same-site neighboring folder (`neighbor_folder_candidates`).
4. Publisher listing candidate (`house_listing_candidate`).
5. Relocated search by file-name stem (`relocated_search` with `search`).
6. Descriptive search through the government index (`relocated_search(...,
   kind='phrase')` with `gov_search`).
7. GovInfo package mapping (`govinfo_document_candidate`, `govinfo_bill_candidate`).

`acquire_candidates` replays only archive captures (rungs 1 and 2). Publisher
leads enter the campaign candidate table (`run_recovery_campaign(candidates=...)`)
and are fetched by `capture_schedule --campaign`.

`pipeline.cutoff_size_hint(record)` reads a failed PDF's stored `body_bytes` and
names a round boundary (1 MiB, 64 KiB, 32 KiB, 1 KiB or a round thousand) that
usually marks a cut-off copy; it is a hint only and never passes or fails a body.

**Web Harvest by file name.** When the exact address in a collection has no
capture, or only the damaged digest, call `webharvest_name_lookup(target,
collection, call, damaged_digest=...)` with the damaged body's base32 SHA-1. It
asks that harvest for the file name across the publisher's site (each House or
Senate subdomain is its own site) and keeps a capture only if it has the same
base name (case-insensitive), the PDF media type, another address and another
digest. `webharvest_collections(year)` names the harvests that close the
document's Congress and the next; callers without a date query as before.
Replayed over the answers recorded for 49 damaged files (ct-z4w5), it kept a
lead for 19, mostly at the publisher's pre-2012 addresses. `acquire_candidates`
replays a name match only at its recorded harvested address, on the target's
site, under the target's base name; with `damaged_body` it records
`shared_prefix`, the count of leading bytes both bodies share. That count is
evidence, not a rule, until real fetches set a threshold. It cannot see a
different document with the same name on the same site, a renamed copy (one had
`1` added to its name), or a document published between two harvests: files
from 2011 exist in the harvest only as the same damaged bytes. The Library of
Congress web archive answers plain clients with a bot check (HTTP 403), so it is
not a rung and must not be worked around.

**Neighboring folder.** For a `/wp-content/uploads/YYYY/MM/<file>` target it
proposes the same file name one month either side (at most six) on the same
host, without a request. Its `mapping` records the only claim: same host, same
file name. Bytes identical to the damaged body reuse its failed qualification by
digest, so they never pass. It cannot see renamed copies (one found on
2026-11-18 had a date prefix added), other folder layouts or hosts, or copies
further than the chosen months.

**Government index.** `gov_search()` posts only `query` and `k` to Firecrawl's
free government index (`/v2/search/gov`), with no credential and a zero-cost
reservation. Send the file name's words, a readable date and the committee, not a
bare stem; stem validation is unchanged. For 49 damaged files (ct-z4w5) it
returned an official hearing print for 34, and 15 of those matched the file's
date in MODS. It cannot see documents outside that index, filter hosts on the
server (the caller's allowed hosts filter its rows), or page past `k` rows. A hit
is usually the hearing that contains the testimony
(`requested_content_in_official_hearing`), not the requested file.

**Manual last step.** When the maintained rungs are exhausted, a manual Google
search through SerpApi is the standing last step for edge cases before a
document is called unrecoverable. It is run by hand, capped, treated as leads
only, and deliberately not wired into the pipeline. The query shape that worked
on 2026-11-18: surname, what the hearing was about when known, the year only,
the committee's name, and `testimony pdf`, with no exact date and no site
restriction. Two of its hits exposed the neighboring-folder pattern.
