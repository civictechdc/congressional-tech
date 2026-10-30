---
id: ct-93zs
status: open
deps: [ct-pocg, ct-w8dc]
links: []
created: 2026-10-30T14:10:03Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, viewer-publication, model, committee-explorer]
---
# Publish useful HTML metadata through the maintained archive and Explorer outputs

Metadata has no user benefit if it stops at extraction. Carry selected fields and evidence into the actual release tables used by readers.

User value: richer descriptions and reliable source dates appear in real search/detail results, while stable document links and bounded browsing continue to work.

Evidence: docs/experiments/extruct-metadata-20261030/report.md and summary.json. Full extraction and comparison artifacts are under output/extruct-metadata-20261030/ (local, Git-ignored); preserve portable fixtures and manifests needed for tests rather than relying solely on these local paths.

## Design

Owners: model/ reading/release schemas and SQL, viewer_publication, and apps/committee_youtube/src/committee_explorer only while it remains an active separate consumer. Extend the maintained native publication path. Related ticket ct-gi01 owns the broader Explorer migration; coordinate its current ownership and do not create another writer or resurrect retired routes.

Publish compact typed descriptions, distinct publication/modification dates with precision, and publisher labels. Put raw metadata and large text behind detail/evidence references. Resolve declared URLs in their capture context and keep original addresses. Record metadata selection and conflict evidence. Update release-schema meanings and compatibility fixtures together.

## Acceptance Criteria

- One actual generated release contains the selected enriched values, source references, and explicit conflicts; no populated field is silently dropped by an exporter.
- Every active consumer path is inventoried; the archive and any still-active committee Explorer tables agree on the meaning of the new fields.
- A webpage modification does not change hearing/document identity, archive capture dates, or existing stable links.
- Older releases remain readable under the declared compatibility policy; new schema changes are versioned and validated.
- Browse operations do not load raw HTML/full article text. Measure release/browse-column size changes and prove evidence is available on demand through the maintained release format.

