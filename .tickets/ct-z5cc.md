---
id: ct-z5cc
status: in_progress
deps: []
links: [ct-t906, ct-te1p]
created: 2026-10-30T14:32:31Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, infra, cloudflare, r2, track5]
---
# T5.3: Replace Cloudflare origin rules deployment via Wrangler or Terraform cloudflare_ruleset

Per docs/plans/bindings-20261025.md §3.4 and infra/cloudflare/congressional-data-r2-edge.json: apply CORS, cache headers, CSP, and ?filename= via Wrangler or Terraform cloudflare_ruleset (replacing apply_r2_edge_rules.py and removing the legacy firewall path allowlist).

## Acceptance Criteria

Cloudflare origin rules (CORS, cache headers, CSP, ?filename=) are managed declaratively via Wrangler or Terraform cloudflare_ruleset, apply_r2_edge_rules.py is retired, and the legacy path allowlist is removed.

