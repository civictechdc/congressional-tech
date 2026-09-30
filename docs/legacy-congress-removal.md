# Congress exploration removal: intent audit

The two unused Congress exploration commands are retired after preserving their
remaining acquisition capabilities in `congress-meetings` and
`congress-committees`. The owner explicitly required both ports before removal.
This audit covers code and interfaces, not deletion of source data or caches.

## Original purpose and consumers

The July 2025 experiment fetched Congress committee/event data to explore its
relationship to committee YouTube channels (`d31d724`). It added XML retries for
broken JSON endpoints (`3013c5b`), moved raw caches into TinyDB (`ec66c97`), and
added committee/event analysis (`e2dc08f`, `4da140e`). Analysis ultimately printed
YouTube database handles for committees with events; it did not publish site JSON.
The old fetch command collected committee details but only discovered event URLs;
full event capture required calling `process_events()` separately.

Repository import/entrypoint searches found no production callers outside these
tools. Workflow history searches for `congress-fetch` and `congress-analyze`
returned no invocations. The earlier `update-youtube.yml` at `48f9a1c` ran
`youtube-fetch` and `youtube-analyze`. Current `update-data.yml` runs those same
YouTube commands plus `congress-meetings`, GPO collectors/matching, chamber
readers, inventory and `congress-committees`.

## Useful behavior accounted for

Paths in this table are relative to `packages/congress_api/src/congress_api/`.
The removed implementation can be inspected in Git at `e7ab15e`.

| Removed group | Original intent / useful behavior | Replacement or explicit retirement |
| --- | --- | --- |
| `legacy/fetch/congress_event_fetcher.py`, fetch command | Paginate meeting listings, cache full events, recover broken JSON endpoints as XML | `meetings.py` already handles pagination, updates, pending retries and atomic snapshots. Added XML recovery via `congress_source.meeting_from_xml`; exact bytes remain in `_source_xml`. |
| `legacy/fetch/congress_committee_fetcher.py`, `legacy/committee_details.py` | Collect committee summaries and full detail/history; reuse cached details | `committee_metadata.py` retains Congress-scoped lists plus full `CommitteeDetail`, endpoint and observation time. Deduplicates endpoint requests, backfills absent details, reuses historical details and refreshes current endpoints. |
| `legacy/committee_summary.py` | Source-preserving committee objects, parent/child traversal and shared identity | `models.congress` preserves native values; `adapters/committees.py` and `adapters/committee_metadata.py` own normalized hierarchy. Unused mutable object registry and traversal helpers are retired. |
| `legacy/committee.py`, `legacy/analyze/main.py` | Group events by committee and associate subcommittees with parent YouTube channels | Meeting/committee adapters and inventory retain these associations. `committees.parent_code` and the separate `youtube_api.tables` retain channel lookup. The exploratory stdout of database handles has no consumer and is retired. |
| `api.py`, `xml_to_dict.py` | Minimal HTTP, pagination and XML conversion | Existing production gateway/listing loops replace HTTP/pagination. `congress_source`, `models.congress_xml`, `models.xml` and `RawContent` retain complete XML; recovery interprets only known field shapes. The lossy generic XML-to-dict wrapper is retired. |
| `legacy/json_to_tinydb.py` | One-time conversion of hard-coded old JSON paths to TinyDB | No current caller or acquisition requirement. Converter retired; no saved data removed or converted. |
| Old `fetch/`, `analyze/`, `json_to_tinydb.py` aliases and package initializers | Keep earlier imports/commands working | Removed by explicit owner decision. `fetch/rejected.py` was only an alias; production `retention/rejected_pages.py` remains. |
| Experimental `packages/congress_legacy` | Proposed separate home for the same code | Abandoned after the owner chose deletion. Not retained as another maintenance surface. |

The earlier analysis bug repair became unnecessary once its entire unused caller
path was removed. It is not a reason to retain a second analysis implementation.
Legacy-only wrapper/cache tests are removed with their targets; source-model,
raw XML, normalization, HTTP and production retention tests remain.

## New capture behavior

Meeting detail HTTP 500 or invalid JSON triggers an XML request through the
existing paced/retrying gateway. Successful JSON makes no extra request.
403/404/429 and other transport failures stay failures. Known lists and integers
are interpreted for current meeting readers, and identifiers remain strings.
The entire XML body survives into source evidence. Bad or mismatched XML cannot
replace an existing meeting; the failed response and URL remain retryable.

Committee snapshots retain the original Congress-specific `committee` alongside
`detail`, `detail_url` and `detail_retrieved_at`. Detail endpoints span Congresses,
so current type/status never replaces historical list values. History, website,
linked counts, parent/subcommittee references, unknown fields, nulls and empty
values survive source capture and the existing normalization adapter. Each
endpoint is fetched once per run. Missing details are backfilled; endpoints in
refreshed Congress lists are refreshed; other retained details are reused.
Invalid detail JSON is retained separately; any failed detail prevents replacement
of the prior snapshot. No new storage service or data migration is required.

## Verification and limits

Executed locally: **993 tests and 31 subtests passed** with
`.venv/bin/python -m pytest -q tests packages/committee_meeting/tests`.
All ten installed production commands and both YouTube commands return help.
Nine production help outputs match the pre-removal snapshot byte for byte;
`congress-committees` changes only its description. A clean wheel excludes all
retired modules and entrypoints. Old generated `build/lib` files were cleared
before that packaging check. `git diff --check` and devcontainer shell syntax
checks pass; workflows and the YouTube package have no diff.
Local logs and the wheel are under `.cache/congress-retirement/`.

The strict `offline-python.py` run exposed an existing localhost-only HTTP test
that its blanket network block prevents from running. The normal test runner
passes that test; no external source refresh was performed. A stale collector
mock was updated to support the new committee-detail request before the passing
full-suite run.

- `test_congress_xml_recovery.py`: retained real Senate XML, list/identifier
  fidelity, full source bytes through normalization, successful JSON, XML
  recovery, unusable/mismatched XML and non-recoverable HTTP failures.
- `test_committee_details.py`: real House/Senate detail fixtures, unknown fields,
  shared endpoints, cache refresh, unchanged historical classification/domain
  IDs, source evidence, rejected details and successful retry.
- Existing collection, source-model, exporter, HTTP, retention and boundary tests
  cover production behavior. The boundary gate checks all ten production CLI
  imports with TinyDB, youtube-api and the retired package blocked.
- The YouTube package, its TinyDB dependency, production workflow and source
  caches remain unchanged. `gpo-match`/inventory still consume its saved JSON.
- This change is locally tested. It does not perform a historical refresh,
  establish live endpoint availability, or claim a GitHub Actions run.

Removed public interfaces: `congress-fetch`, `congress-analyze`,
`congress_api.legacy`, `congress_api.fetch`, `congress_api.analyze`,
`congress_api.api`, `congress_api.xml_to_dict`, and `congress_api.json_to_tinydb`.
Use the two production collectors described in the
[package README](../packages/congress_api/README.md#common-workflows).
