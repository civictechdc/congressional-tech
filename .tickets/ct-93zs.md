---
id: ct-93zs
status: closed
deps: [ct-pocg]
links: [ct-w8dc, ct-m104, ct-t915, ct-5kto, ct-gi01, ct-jnm9, ct-o7t4, ct-c5xf, ct-082q]
created: 2026-10-30T14:10:03Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, viewer-publication, model, committee-explorer]
---
# Publish cited HTML dates, descriptions and labels in the shared release

Make retained page facts available to both readers through the existing native publication. Map the selected readings into the six detail fields `description`, `published_on`, `modified_on`, `publisher_labels`, `page_metadata`, and `main_content`. Keep the list output compact. The Round 2 branch carries the native implementation. `ct-gi01` owns the broader field inventory and `ct-5kto` owns legacy publisher retirement.

## Acceptance Criteria

- An actual generated release exposes compact typed descriptions, publication and modification dates, publisher labels, alternatives and cited main-content references. Preserve date precision, reject template descriptions, resolve declared URLs in capture context and keep literal addresses. Explain any absent facts.
- Preserve event, document and capture date meanings, stable IDs and links. The 2017 Indian Affairs hearing keeps its event date beside its 2025 page update. The Banking Powell fixture keeps the actual witness without promoting committee officials or a CMS author. Internal admin-host canonicals and conflicting dates cannot change identity.
- Verify the mapping and optional-field fixtures on the maintained native path. Version the release schema and validate old-release reads, generated-client compatibility and old-record round trips. Keep date-only and unzoned precision. Inventory active consumers and verify agreement on field meaning without adding a second publisher.
- Measure changed release and browse sizes. Keep raw metadata and larger text behind on-demand evidence references. Cite exact body and source location for dates, advisory or press-release labels, descriptions and text.

## Notes

**2026-10-30T20:37:07Z**

Coordinate with reopened ct-gi01 under PHASE-2 §4.6. The end state is one native publication for site and MCP. Any separate Explorer output is transitional; map selected HTML fields into the maintained model and preserve evidence. Local work may proceed without waiting for the production switch.

**2026-11-02T13:05:13Z**

2026-11-02 (lead): publish HTML metadata as native release columns through the shared release, not through adapters/page_metadata.py, which is reachable only from the old Explorer and is retired in ct-5kto. Round 3 (ct-4thc, ct-jnm9) depends on those columns.

**2026-11-02T13:14:11Z**

2026-11-02 (lead): publication: six new detail.parquet columns, list unchanged; selection logic moves into model SQL and page-signals.json; adapters/page_metadata.py does not survive (it's deleted with ct-5kto).

**2026-11-05T17:11:15Z**

Consolidation accepted 2026-11-05: absorb ct-w8dc.

User outcome: Map and publish useful HTML fields in the maintained native model.

Remaining acceptance: Hearing versus page-update dates; person-card negative controls; precision, conflicts, canonical-URL safeguards and citations; actual generated release; stable IDs; compatibility and bounded browse reads.

Source evidence and full original criteria remain in: .tickets/ct-w8dc.md:27; .tickets/ct-93zs.md:27; .cache/rounds/r2/html/plan.md:89. The superseded records remain available; completed work is reused and unfinished criteria stay with this owner.

**2026-11-05T19:53:12Z**

Closed as superseded on 2026-11-05. ct-082q owns all remaining scope, acceptance and evidence as one HTML delivery feature across extraction, native publication, site, MCP and shared verification. This is consolidation, not a claim that implementation or publication is complete. Original criteria and historical notes remain here; ct-082q links back to them.
