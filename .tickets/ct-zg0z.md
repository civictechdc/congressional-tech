---
id: ct-zg0z
status: open
deps: [ct-bol5, ct-jeku]
links: [ct-0a35]
created: 2026-11-25T20:29:35Z
type: task
priority: 1
assignee: mikewolfd
tags: [ddk-migration, publication, iceberg, serenedb]
---
# Emit DDK release catalog and Iceberg v2 sidecar beside archive manifest

Extend `packages/viewer_publication/src/viewer_publication/archive_publish.py` to emit an additive DDK release catalog (`current.json`, `ddk.lock.json`, `catalog.jsonld`, Iceberg v2 metadata under a parallel prefix) pointing zero-copy to the already-uploaded archive Parquet objects, using the shared DDK bridge adapter (`data-design-kit` `ddk-m8rm`), and bind the release-pinned SereneDB body-text export (`BodyTextSSOT.iter_serenedb_documents` / `ct-0a35`) to the same release ID. Lets the shared DDK Viewer, DDK MCP server, and SereneDB runtime serve live Congressional archive data in shadow mode with zero disruption to `apps/site` or `viewer-publications/manifest.json`.

## Design

Additive sidecar only; leave `viewer-publications/manifest.json` and `releases/<id>/manifest.json` untouched for `apps/site` and `apps/explorer_mcp`. Reuse `ddk.publication` (`dry_run_remote_publication`, `verify_parquet_schema_parity`, `verify_http_consumer_readback`) and `data-design-kit` `ddk-m8rm`. Non-goal: do not refactor `apps/site` or `apps/explorer_mcp` internals (cold-swapped after shadow parity).

## Acceptance Criteria

(1) Archive publish/dry-run produces an additive DDK sidecar (`current.json`, `ddk.lock.json`, `catalog.jsonld`, Iceberg v2 metadata) referencing existing immutable Parquet objects with zero duplicate Parquet uploads. (2) `ddk.publication.dry_run_remote_publication` and anonymous `verify_http_consumer_readback` (with `declared_schemas`) pass while existing `apps/site` and `apps/explorer_mcp` contract tests remain green. (3) Sidecar binds the exact release-pinned SereneDB body-text export (`BodyTextSSOT.iter_serenedb_documents` / `ct-0a35`) so search results resolve to the same release ID and document/page locators.

