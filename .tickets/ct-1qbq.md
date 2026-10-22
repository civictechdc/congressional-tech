---
id: ct-1qbq
status: closed
deps: []
links: [ct-84xa]
created: 2026-10-22T11:11:43Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-8kl2
tags: [r2, security, cloudflare, viewer_publication]
---
# Guard Cloudflare R2 Content-Disposition transform rule against ?filename= header injection in apply-r2-edge-rules.py

In scripts/publication/apply-r2-edge-rules.py, the Cloudflare Response Header Transform Rule concatenated http.request.uri.args['filename'][0] into Content-Disposition without guarding against double quotes, backslashes, semicolons, path separators, or control characters in the rule expression.

## Design

1. Add strict character validation to the pdf-filename-disposition and non-pdf-filename-disposition rule expressions in scripts/publication/apply-r2-edge-rules.py (rejecting '"', '\\', ';', '/', '..', '\r', '\n' and enforcing length bounds) so any unsafe ?filename= parameter is ignored at the edge and falls back to the static R2 Content-Disposition header.
2. Add unit tests in packages/viewer_publication/tests/test_r2_edge_rules.py verifying the Cloudflare expression guards against quote/delimiter injection.

## Acceptance Criteria

1. apply-r2-edge-rules.py plan/verify-config emits transform expressions that reject quote, backslash, semicolon, slash, and control-character injection in ?filename=.
2. All unit tests in test_r2_edge_rules.py pass.


## Notes

**2026-10-22T15:38:56Z**

Verified strict header-injection validation in scripts/publication/apply-r2-edge-rules.py and unit tests in packages/viewer_publication/tests/test_r2_edge_rules.py.
