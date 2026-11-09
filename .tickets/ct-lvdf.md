---
id: ct-lvdf
status: open
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

Size M. Plan: docs/plans/org-entities-20261108.md (Exposure). Add organizations, organization_ids, witness_organizations, organization_redirects to model/registries/release-schema.json with identity organizations.org_id, relationships and an 'appearances by organization' recipe. apps/explorer_mcp needs no reader code (search_entities/get_entity follow published identity); update the server instruction that witnesses are not deduplicated (organizations are linked, people are not). apps/site: witness rows link their organization; an organization page lists appearances and IDs and follows redirects. Can ship after phase 2 with federal orgs only.

## Acceptance Criteria

1) MCP and site contract tests resolve an org, its appearances and a redirected org_id. 2) Across two consecutive releases every prior org_id resolves to a live org or a redirect chain ending at one. 3) The release notes state linked share by appearances and that unlinked strings remain as text.

