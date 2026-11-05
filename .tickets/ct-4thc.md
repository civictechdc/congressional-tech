---
id: ct-4thc
status: closed
deps: [ct-93zs]
links: [ct-082q]
created: 2026-10-30T14:10:03Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, site, explorer]
---
# Show hearing dates, page dates and document descriptions clearly

Help site users find the right hearing and understand what a document is. Use the published fields from `ct-93zs` for separately labeled hearing, publication, and page-update dates. Show selected descriptions, publisher labels, and bounded previews. Load larger content and source evidence on demand.

## Acceptance Criteria

- Browser checks on an actual generated release cover a hearing/page-update split, a conflict with alternatives and source evidence, an advisory, a testimony page, and missing optional fields.
- Keep the published precision and timezone meaning. Show labels and dates faithfully, omit missing optional values, and let users open source evidence and selected text safely. Publisher markup never executes.
- Existing search, filter and deep links work with their documented meanings. Older supported releases render, and browse requests avoid full raw metadata and text. Record representative browser evidence. Image and social discovery stay deferred.

## Notes

**2026-11-05T19:53:12Z**

Closed as superseded on 2026-11-05. ct-082q owns all remaining scope, acceptance and evidence as one HTML delivery feature across extraction, native publication, site, MCP and shared verification. This is consolidation, not a claim that implementation or publication is complete. Original criteria and historical notes remain here; ct-082q links back to them.
