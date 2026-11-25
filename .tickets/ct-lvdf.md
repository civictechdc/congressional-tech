---
id: ct-lvdf
status: closed
deps: [ct-w34j]
links: []
created: 2026-11-09T00:52:02Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-lwxs
tags: [entities, organizations, mcp, site]
---
# Org entities phase 4: publish organizations in the release, MCP and site

Size M. Plan: docs/plans/org-entities-20261108.md (Exposure, Stable IDs and churn). Ships right after phase 2 (string/bag grouping + RefSpec federal agencies) so users get org pages and MCP search immediately; 1-hop `organization_redirects` (AC #2) absorb any later merges when optional phase 3 Wikidata (`ct-39u8`) lands.

- model/registries/release-schema.json: organizations (identity org_id), organization_ids, witness_organizations, organization_redirects; relationships and an 'appearances by organization' recipe.
- Extend `get_entity` in `apps/explorer_mcp/src/congressional_explorer_mcp/reader.py` for `organizations`. Resolve a retired `org_id` through its latest `organization_redirects` entry to the live row in one hop. Return the requested ID in `redirected_from`. Expose organization search and follow `witness_organizations.witness_key` to appearances.
- apps/site: witness rows link their organization; an organization page lists appearances and IDs and follows redirects.

## Acceptance Criteria

1. Reader and site tests look up a live organization, its appearances and a retired ID.
2. Across two releases each prior ID resolves directly or through one redirect. Plant a normalization split where neither new bag holds the old anchor. Both new IDs come from their own anchors. The old ID redirects to the bag with the most distinct verbatim strings inherited from the old bag. An equal count chooses the smaller new bag key in UTF-8 byte order. Reverse the input order and verify the same target.
3. Release notes state the linked share by appearances and retired IDs by cause.

## Notes

**2026-11-22T18:41:11Z**

2026-11-22 ticket backlog audit: Removed blocking dependency on ct-39u8 (Wikidata). Ship Phase 1 (ct-6him) + Phase 2 (ct-w34j) to users first; optional Phase 3 Wikidata anchoring can follow cleanly using 1-hop organization_redirects.

**2026-11-22T19:53:35Z**

2026-11-22 Owner decision A3: Attach Ban, Park & You (APSR 2023, doi:10.1017/S0003055422000405) 9-parent / 18-child witness organization taxonomy to resolved organizations cleanly in parallel with DocMeta V7 (zero blocking dependency on ct-o7j0). Reference: docs/plans/docmeta-v7-consulting-plan-20261122.md.

**2026-11-25T15:01:44Z**

Merged to main in PR #244 (12/12 CI checks green). Publishes organizations, organization_ids, witness_organizations, and organization_redirects in release-schema.json, archive_model/job/controller/release_gate (with prior org custody, 1-hop split UTF-8 tie-break determinism, and canonical appearance share in render_notes), Congress Explorer MCP (get_entity 1-hop redirects + 128 KiB MAX_BYTES budget guard + search_entities), and Astro site (manifest-gated Organizations browse tab, OrganizationDetail, witness/hearing/person links, keyed non-eager Parquet readers).
