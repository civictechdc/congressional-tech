---
id: ct-jeku
status: closed
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


## Notes

**2026-11-27T20:20:03Z**

Verification summary:
- Exported deterministic ODCS v3.2.0 contracts for all 35 archive tables (model/contracts/tables/*.odcs.json), bundle contract (model/contracts/archive-release.odcs.json), and RefSpec/spicycongress URN bindings (model/contracts/refspec-urn-bindings.json), keeping viewer_publication.archive_schema and model/registries/release-schema.json as single owners with zero touches to archive_schema.py, release-schema.json, model/sql/*, publish-model.json, or byte-hashed parser files.
- Validated against ODCS v3.2.0 structural checks (0 errors across all 36 contracts), ddk.documents.validate_document(..., kind='dataset'), ddk.arrow_mapping.EXACT_PROFILE (0 unsupported items), ddk.arrow_observation.observe_declaration (status='passed' across 35/35 tables), and ddk.publication.verify_parquet_schema_parity across 35/35 contracts plus the 5 matching frozen archive-contract fixtures (links, recoveries, sources, urls strict; committees with normalize_arrow_encodings=True).
- Verified live HTTP Range Parquet footer parity against release efd7973e200f05a15c5f9d732d343a3b2bab1ac88915d15b7053cba096d8943c: 32/35 tables clean under normalized unordered parity (27/35 strict, +2 bills/nominations unordered, +3 meetings/recording_matches/videos normalized), and 3 documented producer-SQL extra-column drifts (organization_ids +evidence, witness_organizations +method/score/evidence, roll_call_votes +documents[].nomination_id).
- Hardened verify_live_release_parity (SSRF/IP/DNS/redirect/206/manifest/range-length guards) and enrolled export-odcs-contracts.py --check drift checks in production-offline (test_archive_odcs.py).
