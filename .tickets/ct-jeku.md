---
id: ct-jeku
status: open
deps: []
links: []
created: 2026-11-25T20:29:35Z
type: task
priority: 1
assignee: mikewolfd
tags: [ddk-migration, odcs, schema, refspec]
---
# Export ODCS v3.2.0 contracts and RefSpec URN bindings for archive tables

Generate ODCS `v3.2.0` `DataContract` files and canonical `RefSpec` URN mappings from `packages/viewer_publication/src/viewer_publication/archive_schema.py`, `model/jobs/refspec/refspec.json`, and `model/jobs/spicy-regs/spicy-regs.json`, and validate them against published archive Parquet outputs using `ddk.publication.verify_parquet_schema_parity`. Catches column and identifier drift before publication and supplies the contract inputs needed by `spicycongress` and `SpicyEntities`.

## Design

Emit ODCS `v3.2.0` contracts for all published archive tables (meetings, documents, witnesses/appearances, people, organizations, recordings, committees, bills) with canonical URN mappings matching `spicycongress/datamap/definitions/` (`bill-id`, `bioguide-id`, `house-committee-code`, `house-event-id`, `govinfo-package-id`, `person-id`). Keep `archive_schema.py` as single owner until cutover; do not touch byte-hashed parser files (`captures.py`, `meeting_records.py`, `appearance_records.py`, `house_naming`).

## Acceptance Criteria

(1) Deterministic export produces valid ODCS `v3.2.0` `DataContract` JSON files for all published archive tables derived from `archive_schema.py`. (2) `ddk.publication.verify_parquet_schema_parity` passes against a real published release (or frozen archive contract fixture) with nullability differences explicitly documented or reconciled. (3) Cross-stack identifier columns map cleanly to canonical `RefSpec`/`spicycongress` URNs and CI/local checks reject schema drift before publish.

