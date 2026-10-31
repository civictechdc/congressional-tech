# Recovery evidence integration interfaces

Status: proposed interfaces; implementation and integration are pending.

## Campaign descriptor v1

A UTF-8 JSON document identifies one campaign with `version: 1`, `campaign_id`, `requirement` (`historical_exact`, `requested_content`, or `current_official_counterpart`), and pinned metadata tables. Each table has a local `path` and a lowercase SHA-256 `sha256` of its exact bytes. The descriptor identifies the target table and the candidate membership table by name; the target table contains literal `target_url` values, and candidate membership contains exact (`target_url`, `candidate_url`) pairs. These tables, not URL arrays, define the complete allowed set. All table identities must be verified before scheduling or planning; a changed pin refuses the campaign. This is a proposal until the shared reader and tests land; consumers must not interpret an unverified descriptor as authorization.

## Qualification and identity

Qualification takes a body with established custody, its digest, the validator version/configuration, and tool versions; it returns a reusable result bound to those identities. Mutable local files must regain verified custody before a cache hit. Identity acceptance consumes target requirement, target and candidate URLs, body digest, source receipt and time, qualification, relationship kind, and source-native evidence. Contradictions reject; missing evidence remains unresolved. Qualification alone does not establish identity.

## Import

A campaign stage must pass only accepted, qualified bodies or verified retained references to the existing `corpus_recovery.reconcile` and `import_retained` owners. Existing provenance schema fields remain unchanged. Acquisition and discovery integration depends on their owners' finished interfaces; no second fetcher or publisher is introduced.

## Evidence and lifecycle

Campaign manifests, pinned metadata, ledger, and decisions remain with the campaign audit. Qualification cache entries live while the body and validator identities remain valid; mutable custody must be rechecked. Temporary parser/render files are removed after their consumers finish. Production baseline counts and live-provider acceptance remain unverified.

## Implemented descriptor reader

`congress_shared.campaign.load_campaign(path)` reads version 1 and verifies all pinned metadata files before returning `Campaign`. Exact JSON fields are `version`, `campaign_id`, `requirement`, `tables`, `target_table`, and `candidate_table`; `tables` maps names to `{ "path": ..., "sha256": ... }`. Table paths may be absolute or relative to the descriptor. The target and candidate table names must differ. `Campaign.table_path(name)` checks process-local custody before returning a path; `Campaign.require_custody()` checks all tables after a consumer uses them and before a dependent effect. A new process must reload and reverify. `descriptor_sha256` identifies the exact descriptor bytes.

The reader pins bytes but does not validate Parquet schema, membership, or protect against a concurrent writer during a consumer's scan. The planner and capture owner must validate their table schemas and exact membership, retain the returned custody objects through selection, and check custody after reading before any effect. Stronger atomic snapshots or owner locks are needed if a writer can mutate metadata while a consumer reads it. No consumer is wired yet.

Focused test: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/packages/congress_shared/src:$PWD/packages/congress_api/src:$PWD/packages/corpus_recovery/src" /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -q -p no:cacheprovider packages/corpus_recovery/tests/test_campaign_descriptor.py` — 3 passed. Module paths were verified in this worktree. This is not integrated campaign proof.
