---
id: ct-4nyy
status: open
deps: [ct-jo8n, ct-f11a]
links: [ct-3li2, ct-f11a, ct-jo8n]
created: 2026-10-20T22:15:53Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Use native exports only after news rights and expiry filtering

The news client exposes ExportSpec but no actual export caller uses it. Native export authorizes named columns and every row in one retained group; it does not apply news C5 restrictions or expiry rules. Connect the existing authorized export path to native completion and replay.

## Acceptance Criteria

- Start with one exact published news release and apply maintained analysis/export.py policy, including restricted/metadata-only content, derived copies and capture expiry.
- Export only the authorized exact version and column allowlist, preserving nested values while removing private field metadata and credentials. Do not publish native object URLs as evidence of public authorization.
- Decode output independently and test expiry boundaries, expired captures referenced by versions, old export reads and lost-response replay without rewriting completed output.
- Keep archive/viewer routed assets and review bindings with their current owner; a native whole-group export is optional and never required for a routine incremental update.


## Notes

**2026-10-20T22:15:54Z**

2026-10-20 adoption review: packages/news_lake/src/news_lake/storage/docspec_backend.py (primary checkout). Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.

**2026-10-20T23:32:30Z**

Reopened by evolutionary-refactoring audit at `main` (`8221566d` / `33ce7877`):
1. `DocSpecNewsViews.export_authorized` (`packages/news_lake/src/news_lake/storage/docspec_backend.py:1507-1591`) has no caller outside `tests/test_docspec_backend.py` (not wired to `news_lake.analysis.export` or any release/CLI export entry point).
2. For every exported table, `export_authorized` (`:1530-1538,1564,1575`) stages a separate `export_{logical_dataset}` dataset via `self.client.run_table(...)`, runs `self.client.export(export_spec)` to write a second Parquet file, and then runs `shutil.copyfile(exported_path, dest_file)` to write a third copy, plus `_ensure_release_read` (`:1488-1505`) fabricates dummy UUIDs (`00000000-0000-5000-8000-000000000000`) when passed raw records instead of requiring an exact published release (`ct-jo8n`).
3. Needs lost-response replay and old-export pin readback verification after a newer export channel selection.

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A- | Impl: C+ (Reopened). Enforces C5 export_release before native export, but removing synthetic release UUIDs, triple Parquet writes, and wiring a non-test caller is tracked in ct-f11a.
