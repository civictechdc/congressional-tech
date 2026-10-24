---
id: ct-84xa
status: closed
deps: []
links: [ct-0odd, ct-aia9, ct-ec91, ct-te1p, ct-3ttc, ct-gi01, ct-8kl2, ct-2yl5, ct-bwac, ct-1qbq, ct-t906]
created: 2026-10-22T04:03:02Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-8kl2
tags: [cloudflare, r2, edge, viewer-data, security]
---
# Apply Cloudflare R2 Custom Domain and edge rules for congressional-data.spicygov.ai and retire viewer-data Worker route

Apply the declarative Cloudflare R2 Custom Domain, CORS, WAF allowlist, and Response Header Transform Rules in infra/cloudflare/congressional-data-r2-edge.json to the live spicygov.ai zone so congressional-data.spicygov.ai serves directly from congressional-tech-raw without the apps/viewer-data Worker.

## Design

1. Attach R2 Custom Domain congressional-data.spicygov.ai directly to bucket congressional-tech-raw and remove the legacy viewer-data Worker route.
2. Apply the WAF custom firewall rule from infra/cloudflare/congressional-data-r2-edge.json allowing only GET/HEAD/OPTIONS on /viewer-publications/*, /bodies/sha256/*, and /exports/*.
3. Apply the bucket CORS policy and the 2 conditional Response Header Transform Rules (immutable Cache-Control + nosniff + sandbox CSP on /bodies/sha256/* with RFC 6266 Content-Disposition override when ?download=1, and no-store on pointer.json / CURRENT.json).

## Acceptance Criteria

1. Direct GET/HEAD/Range requests to https://congressional-data.spicygov.ai/viewer-publications/*, /bodies/sha256/*, and /exports/* succeed with expected CORS, Cache-Control, and CSP headers.
2. Requests to non-allowlisted prefixes (e.g. /state/* or /manifests/*) are blocked with 403 by the Cloudflare WAF rule.
3. node apps/site/scripts/verify-live-publication.mjs passes against the live domain.


## Audit 2026-10-24

- Verdict: CANNOT-VERIFY (batch kl2a1aa).
- Grades: proposal 81 → 81, work 62 → 62.
- Problem: `apply` PUTs the zone entrypoint rulesets for `http_request_firewall_custom` and `http_response_headers_transform` (:278, :284).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:28
- Covered by: WS5 (ct-t906), which makes `apply` merge by rule `ref`.
- See docs/reviews/2026-10-24-ticket-audit/README.md
