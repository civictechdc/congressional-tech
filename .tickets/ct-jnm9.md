---
id: ct-jnm9
status: closed
deps: [ct-93zs]
links: [ct-082q, ct-m104, ct-0a37, ct-93zs, ct-o7t4, ct-c5xf]
created: 2026-10-30T14:10:03Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, mcp, explorer]
---
# Give Congress MCP the same cited page facts as the site

Help assistants distinguish when a hearing happened, when a document was published, and when a webpage changed. Read the fields from one pinned shared release. Extend the existing discovery or detail tools only where their generic field access is insufficient.

## Acceptance Criteria

- Against an actual release, retrieve the same description, source type, publication/modification dates and conflict evidence as the site fixture. Discovery explains field meanings and names the selected release.
- Preserve date precision and the difference between event and page dates. Citations resolve to the selected source reading. Tests cover older releases, absent and partial fields, conflicts, and large metadata or text with bounded responses and paging.
- Keep extraction, field selection and identity decisions upstream. Reuse the MCP result in `ct-0a37` and `ct-m104`.

## Notes

**2026-10-30T20:37:07Z**

Link selected HTML metadata acceptance to ct-m104 and PHASE-2 §4.6. Consume the shared native release through existing generic discovery/query support; keep extraction and field selection upstream. This ticket does not own the broader channel/video/research inventory.

**2026-11-05T19:53:12Z**

Closed as superseded on 2026-11-05. ct-082q owns all remaining scope, acceptance and evidence as one HTML delivery feature across extraction, native publication, site, MCP and shared verification. This is consolidation, not a claim that implementation or publication is complete. Original criteria and historical notes remain here; ct-082q links back to them.
