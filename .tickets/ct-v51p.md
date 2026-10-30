---
id: ct-v51p
status: open
deps: []
links: []
created: 2026-10-30T18:34:43Z
type: feature
priority: 1
assignee: mikewolfd
tags: [phase-2, senate, url-key, witnesses]
---
# Strip ColdFusion download query parameter in model/registries/url-rules.json for Senate hosts

D4 full-corpus measurement (`docs/plans/phase-2-annex-20261028.md` §4.2) showed that 5,638 / 8,946 (63.0%) of listed Senate testimony documents match witness card `document_urls` under strict `url_key`, because six Senate committees (`aging`, `appropriations`, `banking`, `budget`, `finance`, `veterans`) use ColdFusion `/download/` URLs where either the witness card or the capture URL appends `?download=1` or `&download=1`. Stripping the `download` query parameter on those hosts raises Senate witness card-to-document matching in `list.parquet` (`witness_keys`) to 8,096 / 8,946 (90.5%).

## Design

Owner: `model/registries/url-rules.json` (and regression tests in `packages/viewer_publication/tests/test_phase2_model_entities.py`).

1. Add a `"kind": "strip"` query-parameter rule to `model/registries/url-rules.json` (which is already consumed by `model/sql/url-normalized.sql:36-43` and hashed by `archive_model_profile.py`):
   ```json
   {
     "kind": "strip",
     "host_pattern": "(^|\\.)(aging|appropriations|banking|budget|finance|veterans)\\.senate\\.gov$",
     "pattern": "^download$"
   }
   ```
2. **No SQL changes** are needed in `model/sql/url-normalized.sql` or `model/sql/document-witness-keys.sql`: `url-normalized.sql` already strips query parameters matching `"kind": "strip"` rules for matching hosts on both `model_url_keys` (archived document URLs) and `appearance_witness_url_inputs` (witness card `document_urls`).
3. **Leave `urls.parquet` (`DATA-MODEL` §8.2 `lookup_url`) untouched:** per `P2R3`, `urls.parquet` hashes exact `lookup_url` (removing only `#fragment`, preserving query strings) whereas `url_key` (`DATA-MODEL` §7.2) applies `url-rules.json`.

## Acceptance Criteria

- `model/registries/url-rules.json` strips the `download` query parameter (`?download=1`, `&download=1`) across `aging`, `appropriations`, `banking`, `budget`, `finance`, and `veterans` `.senate.gov` hosts while preserving other query parameters (such as `id` or `file`) and non-matching hosts.
- Witness card `document_urls` from all six Senate ColdFusion hosts resolve to their archived testimony documents in `document_witness_keys` (`list.parquet` `witness_keys`) when one side carries `?download=1` or `&download=1` and the other does not.
- `urls.parquet` (`lookup_url`, `DATA-MODEL` §8.2) remains unchanged.
- Regression tests in `test_phase2_model_entities.py` verify all six Senate hosts.
