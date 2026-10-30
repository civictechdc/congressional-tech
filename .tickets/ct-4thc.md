---
id: ct-4thc
status: open
deps: [ct-93zs]
links: []
created: 2026-10-30T14:10:03Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, site, explorer]
---
# Show clear hearing, publication, and update dates with useful document descriptions

Users should understand when a hearing happened, when a document was published, and when its page changed without inspecting raw metadata.

User value: clearer search results and detail pages, useful document-type labels, and inspectable evidence for disputed facts.

Evidence: docs/experiments/extruct-metadata-20261030/report.md and summary.json. Full extraction and comparison artifacts are under output/extruct-metadata-20261030/ (local, Git-ignored); preserve portable fixtures and manifests needed for tests rather than relying solely on these local paths.

## Design

Owner: apps/site Explorer/archive readers and presentation components. Consume the published typed fields. Use separately labeled Hearing date, Published, and Page updated values when applicable, preserving date/time precision. Show selected descriptions, publisher document labels, and cleaner text previews; load larger text/evidence only when requested.

Expose consequential conflicts with the retained source and alternatives. Empty optional values remain omitted. Keep established date filters tied to their documented meaning. Preview-image selection/social-account browsing are deferred. This is the requested evidence-backed metadata feature; no separate performance redesign under ct-2wsw is included.

## Acceptance Criteria

- Browser checks use an actual release from the publication task and cover a hearing/page-update split, a date conflict, an advisory, a testimony page, and missing optional fields.
- The displayed dates and document labels match published values and meaning; no missing timezone or precision is invented for display.
- Users can open the relevant source evidence and selected text; unsafe publisher HTML is not executed.
- Search/filter/deep-link behavior remains coherent, and existing supported releases still render.
- Capture representative UI evidence and verify browse requests do not download full raw metadata or full text merely to list results.

