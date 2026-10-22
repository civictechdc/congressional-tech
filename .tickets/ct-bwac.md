---
id: ct-bwac
status: closed
deps: []
links: [ct-8kl2, ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-aia9, ct-2yl5, ct-gi01, ct-a3le]
created: 2026-10-21T20:53:31Z
type: feature
priority: 2
assignee: mikewolfd
external-ref: ss-023x,ss-k3mg,ss-yjvy,ss-msdx,ss-vfm6
parent: ct-8kl2
tags: [congress_api, retention, docspec, union-find, partitioning]
---
# Flatten congress_api/retention routing/splitting/staging (RoutingPages, CatalogRows, 3 Union-Find engines) and receipt re-scans into native docspec-rs operators

congress_api/retention currently maintains ~7,500 lines of Python database machinery on top of docspec-rs: 16-way JSON B-trees (RoutingPages, CatalogMemberships) sharding tables into 64-256 separate docspec datasets, manual source_occurrences sidecar splitting (CatalogRows), three separate Python/SQLite union-find implementations (document_index.py in-memory union-find, catalog_staging.py SQLite union-find, and catalog_scope.py SQLite union-find, plus catalog_dependency_preparation.py DuckDB/SQLite staging), Python read_keys merge loops (_merge_states, merge_values), and three .jsonl.gz receipt line readers.

## Design

Paired with spicy-stack ss-023x (UpdateMergeSpec + FirstValueBy/CollectDistinctWithProvenance), ss-k3mg (PartitionSpec Bucket(N)), ss-yjvy (flat child occurrence column groups), ss-msdx (ConnectedComponentsTransform), and ss-vfm6 (R2 parity):
1. Store extracted HTTP response/redirect/probe metadata columns directly on the captures table in docspec-rs and join to filenames via RefreshSpec, deleting the 3 duplicate .jsonl.gz receipt line readers (document_index.py:retained_records, refresh_response_metadata, document_recovery.py:recover_sources).
2. Key URL-indexed tables (state, alias_sources, target_sources) by deterministic 64-byte SHA-256 hex columns (state_key_sha256 / source_url_sha256, 100% <128B for Parquet min/max pruning per ct-tuez) and PartitionSpec(Transform::Bucket(64)) (ss-k3mg), collapsing 64-256 manual dataset shards into 1 logical dataset per table and retiring RoutingPages, CatalogMemberships, and StateRoutes.
3. Use docspec-rs native flat child column groups for source_occurrences (ss-yjvy), retiring CatalogRows.
4. Keep domain edge/priority policy in Python (Senate &download=1 stripping, connectable_body_key = NULL for HTML/binary/404s and EMPTY_BODY_DIGEST, priority_rank, and document_id SHA-256 formula), and execute component grouping via docspec-rs ConnectedComponentsTransform (ss-msdx) + UpdateMergeSpec (ss-023x), retiring all three Python/SQLite union-find engines (document_index.py, catalog_staging.py, catalog_scope.py) and catalog_dependency_preparation.py.

## Acceptance Criteria

- Each archive/catalog table is stored as 1 logical docspec-rs dataset with Bucket(N) + 64-byte SHA-256 key pruning matching or beating RoutingPages latency on 8.13M rows.
- Document equivalence classes and attribute rollups are computed by docspec-rs ConnectedComponentsTransform with zero Python sqlite3/DuckDB scratch files, zero .jsonl.gz receipt re-scans, and 100% identical document_id and source_id hashes.
