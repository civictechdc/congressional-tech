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
- apps/explorer_mcp: no reader code (search_entities/get_entity follow published identity); revise the instruction that witnesses are not deduplicated (organizations are linked, people are not).
- apps/site: witness rows link their organization; an organization page lists appearances and IDs and follows redirects.

## Acceptance Criteria

1) MCP and site contract tests resolve an org, its appearances and a redirected org_id. 2) Across two consecutive releases every prior org_id resolves in one hop to a live org. 3) Release notes state the linked share by appearances and retired IDs by cause.
