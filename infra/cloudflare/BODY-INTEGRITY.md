# Preserve archived body bytes

The public R2 domain serves content-addressed archived bodies. Cloudflare email obfuscation must be off only for that hostname and body path. The stored object remains unchanged; verification compares ordinary public GETs with the original SHA-256.

The declaration is `configuration_rules[0]` in `congressional-data-r2-edge.json`. Terraform exports it as `public_r2_body_integrity_rule`. There is deliberately no new `cloudflare_ruleset` resource for `http_config_settings`: the pinned provider owns a whole phase, while this project owns one rule. Existing response-header rules remain separate.

Use this exact configuration rule:

```json
{
  "ref": "public-r2-content-addressed-body-no-email-obfuscation",
  "description": "Preserve exact archived body bytes on the public R2 custom domain",
  "expression": "(http.host eq \"congressional-data.spicygov.ai\") and starts_with(http.request.uri.path, \"/bodies/sha256/\")",
  "action": "set_config",
  "action_parameters": {"email_obfuscation": false},
  "enabled": true
}
```

Place it last in the zone's `http_config_settings` entrypoint. Preserve every unrelated rule and its relative order. Do not change the zone-wide email setting or replace the phase ruleset. Configuration rules apply in order; later matching settings win. [Cloudflare configuration rules](https://developers.cloudflare.com/rules/configuration-rules/), [email obfuscation](https://developers.cloudflare.com/waf/tools/scrape-shield/email-address-obfuscation/).

For a dashboard application, create a Configuration Rule with the description above as its name, paste the exact expression, and set only **Email Obfuscation → Off**. A dashboard-generated rule reference requires explicit ownership review before any later automated PATCH; a matching description alone does not establish ownership.

For an API application, first obtain a successful readback of the existing phase and retain it as JSON with its HTTP status:

```json
{"status":200,"data":{"success":true,"result":{"id":"...","kind":"zone","phase":"http_config_settings","rules":[]}}}
```

That example describes the response shape; do not substitute it for an actual read. The planner rejects permission failures, unknown phases and duplicate references. It emits only a rule append or a PATCH to the exact owned reference's verified ID, moving that rule last when needed:

```sh
.venv/bin/python -m viewer_publication.apply_r2_edge_rules plan-config \
  --observed CONFIG-PHASE-READBACK.json \
  --zone-id 7047ad6a69b297401637b2c9dcb8949c
```

The command performs no HTTP mutations. Read the phase again before applying its per-rule operation through the official API, preserving unrelated rules. If no phase exists, create the scoped rule through the dashboard or explicitly review phase creation; a 403 or 404 is never treated as an empty phase by this planner. Relevant permissions are zone-scoped **Config Settings Read/Write**. The existing Wrangler OAuth login can read the R2 binding and Workers routes but cannot inspect these configuration rules. [Cloudflare configuration API](https://developers.cloudflare.com/rules/configuration-rules/create-api/).

Before and after an authorized change, retain separate evidence files:

```sh
.venv/bin/python -m viewer_publication.apply_r2_edge_rules verify-body \
  --repeats 2 --out /ABSOLUTE/DURABLE/PATH/body-delivery-after.json
```

This runner uses the original failing HTML object from the declaration, not a substituted sample. It requests ordinary 200 responses with identity and gzip encodings, decodes only declared transport gzip, and enforces the original 19,492-byte/SHA-256 identity within a 64KiB bound. It records failed checks and exits nonzero on a mismatch. It uses no Range request, reconstructed HTML or integrity bypass. Existing evidence files are never overwritten. A successful after-run must precede resuming the retained indexing work.
