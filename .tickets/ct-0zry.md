---
id: ct-0zry
status: closed
deps: []
links: []
created: 2026-11-17T20:17:27Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-ihe7
tags: [docmeta]
---
# DocMeta sidecar: one-release migration script and a hand-rolled sweep resume

Two things adopted as they were in ct-ihe7. (1) scripts/build_v6_2_ssot_sidecar.py turns the v6_1 bundle into v6_2 for release 55c14dcd with fixed row counts; its v6_1 predecessor (build_v6_1_hydrated_sidecar.py, 3,509 lines) is still only in .cache/archive-release/docmeta-v6-20261116/scripts_v6_1. The pinned v6_2 files predate rules R4 to R8. (2) parquet_runner_v6.py keeps its own resume keys, part files and atomic writes; under the engine-first rule, decide whether that belongs to a docspec-rs operation. publish-model.json still binds no docmeta_v6_1 input (ct-fk4w).

## Acceptance Criteria

A builder that takes a release and writes the three sidecar parts with current rules, tested on a bounded sample; a decision recorded on the sweep's resume layer.


## Notes

**2026-11-20T17:29:15Z**

2026-11-20: Built release-parameterized DocMeta v6 sidecar builder (packages/congress_docmeta/src/congress_docmeta/sidecar_builder.py and scripts/build_docmeta_sidecar.py) applying current rules R4-R8, verified on bounded sample in test_docmeta_audit_remediation.py, and documented sweep resume design in packages/congress_docmeta/docs/architecture.md (commit 0e554d3f; CI run 44776340037).
