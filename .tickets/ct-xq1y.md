---
id: ct-xq1y
status: closed
deps: [ct-oxg6]
links: [ct-oxg6, ct-5fkx, ct-tw3r]
created: 2026-10-20T23:52:13Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, rust, contract, validation]
---
# Enforce deny_unknown_fields across native request specs so callers cannot silently drop fields

docspec-rs/src/model.rs enforces #[serde(deny_unknown_fields)] on RefreshSpec (:408), GenerationSeal (:224), ContinuousBackfillSpec (:961), and DependencyCorrection (:991), but omits it on RunSpec (:850), InputSpec (:868), UpdateSpec (:875), SchemaSpec (:928), and BackfillSpec (:948). Because UpdateSpec lacked deny_unknown_fields, packages/news_lake/src/news_lake/storage/docspec_backend.py:924-925 sent spec['relationship'] = relationship to POST /updates/run and serde silently discarded the field instead of refusing the mismatched request contract (ct-5fkx).

## Acceptance Criteria

- Add #[serde(deny_unknown_fields)] to public request/spec structs in docspec-rs (RunSpec, InputSpec, UpdateSpec, SchemaSpec, ColumnAddition, BackfillSpec, ComputedField, GroupDefinition, ExportSpec, ExportPolicy, CompactionSpec, EvidenceSpec) unless an explicit versioned extension field exists.
- Add serde unit/HTTP tests verifying that unknown fields in JSON requests to /run, /updates/run, /schemas/run, /backfills/run, /exports/run, and /compactions/run are refused with a 4xx validation error rather than silently ignored.
- Reconcile UpdateSpec relationship handling with ct-5fkx so docspec_backend.py:924-925 never sends an unacknowledged field.


## Notes

**2026-10-20T23:53:21Z**

CS 300 Grade — Spec: A | Impl: N/A (Open). Created to close silent field-dropping on RunSpec, InputSpec, UpdateSpec, SchemaSpec, and BackfillSpec in docspec-rs/src/model.rs:850-957 that masked the UpdateSpec relationship mismatch in ct-5fkx.

**2026-10-21T00:31:34Z**

Implemented in docspec-rs: added #[serde(deny_unknown_fields)] to RunSpec, InputSpec, UpdateSpec, ComputedField, BackfillSpec, and GroupDefinition. Added src/model.rs tests proving unknown fields are refused and that UpdateSpec relationship parses explicitly. cargo test --lib: 367 passed. Commit pending.

**2026-10-21T00:58:53Z**

CS 300 Post-Review Fix -> Grade: A. Added http_routes_refuse_unknown_fields_with_422 in docspec-rs/tests/http_optional_changes.rs:117-202 verifying HTTP 422 refusal on /run, /updates/run, /schemas/run, /backfills/run, /exports/run, and /compactions/run when unknown JSON fields are supplied.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch mi03b).
- Grades: proposal 94 → 94, work 90 → 92.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
