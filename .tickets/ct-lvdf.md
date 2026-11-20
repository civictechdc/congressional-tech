---
id: ct-lvdf
status: open
deps: [ct-w34j, ct-39u8]
links: []
created: 2026-11-09T00:52:02Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-lwxs
tags: [entities, organizations, mcp, site]
---
# Org entities phase 4: publish organizations in the release, MCP and site

Size M. Plan: docs/plans/org-entities-20261108.md (Exposure, Stable IDs and churn). Ships only after phase 3, so the first published org IDs already carry their registry and Wikidata anchors and the bag-ID redirect churn happens before anything is public.

- model/registries/release-schema.json: organizations (identity org_id), organization_ids, witness_organizations, organization_redirects; relationships and an 'appearances by organization' recipe.
- Extend `get_entity` in `apps/explorer_mcp/src/congressional_explorer_mcp/reader.py` for `organizations`. Resolve a retired `org_id` through its latest `organization_redirects` entry to the live row in one hop. Return the requested ID in `redirected_from`. Expose organization search and follow `witness_organizations.witness_key` to appearances.
- apps/site: witness rows link their organization; an organization page lists appearances and IDs and follows redirects.

## Acceptance Criteria

1. Reader and site tests look up a live organization, its appearances and a retired ID.
2. Across two releases each prior ID resolves directly or through one redirect. Plant a normalization split where neither new bag holds the old anchor. Both new IDs come from their own anchors. The old ID redirects to the bag with the most distinct verbatim strings inherited from the old bag. An equal count chooses the smaller new bag key in UTF-8 byte order. Reverse the input order and verify the same target.
3. Release notes state the linked share by appearances and retired IDs by cause.
