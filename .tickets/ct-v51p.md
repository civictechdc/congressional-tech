---
id: ct-v51p
status: closed
deps: []
links: [ct-30fp, ct-aapl, ct-5esu]
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

## Notes

**2026-11-01T03:09:00Z**

Added senate-coldfusion-download strip rule in model/registries/url-rules.json for aging, appropriations, banking, budget, finance, and veterans .senate.gov hosts; added fixture cases in model/fixtures/url-key-cases.json and end-to-end witness document matching test test_senate_coldfusion_download_query_stripped_in_witness_document_matching in packages/viewer_publication/tests/test_phase2_model_entities.py. Verified with test_url_keys.py, test_normalized_pipeline.py, and test_phase2_model_entities.py.

**2026-11-01T10:38:19Z**

Independent Validation Audit (2026-11-01, validator 97de9ecd):
- Verdict: PASS-WITH-CAVEATS (3/4 ACs fully met, 1 partial test combination; 9,111 keyed_universe URLs and 5,082 merged key groups verified with 0 document merges/splits in publish_v20).
- Remaining work before closure:
  1. [Priority 2] In packages/viewer_publication/tests/test_phase2_model_entities.py:929-1008 (`test_senate_coldfusion_download_query_stripped_in_witness_document_matching`), add the 4th explicit combination `testimony-d` (`capture bare /download/testimony-d` vs `witness card /download/testimony-d&download=1`) required by AC 4.
  2. Commit working-tree changes; live release regeneration (`publish_v21+`) and public pointer advancement tracked under ct-77zb / ct-gi01.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 3 Engineer (ddaead05, 99% confidence):
  1. Extended `test_senate_coldfusion_download_query_witness_links_join_across_all_committee_hosts` in `test_phase2_model_entities.py:994-1084` with the 4th explicit query combination (`testimony-d`: bare capture URL vs `&download=1` witness link) alongside `?download=1` vs `&download=1`, `&download=1` vs `?download=1`, and `?download=1` vs bare across all 6 Senate ColdFusion committee hosts.
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (99%), Green Team PASS (100%), Greybeard PASS (100%), Evolutionary Refactoring PASS (100%).
