---
id: ct-4nyy
status: open
deps: [ct-jo8n]
links: [ct-3li2, ct-f11a, ct-jo8n, ct-d8cf, ct-a1aa, ct-a3le, ct-mi03]
created: 2026-10-20T22:15:53Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-d8cf
tags: [docspec, application-adoption, efficiency]
---

# Export only the news content the selected release allows

**Parked News Lake work.** The CLI already exports native Parquet. Its default full read supplies captures, but a versions-only request can omit the capture evidence used to determine expiry. Both existing policy preparations can then treat missing evidence as no expiry and select an unredacted direct export. Native capture expiry also compares variable-precision timestamp strings lexically. The optional destination overwrites fixed filenames, so an earlier returned path can later name different bytes.

## Smallest useful change

Resolve the available release once through `ct-jo8n`. Use its pinned captures to decide expiry even when captures are not requested as output. Apply one native C5 access policy with typed chronological comparison and an explicit column allowlist. Preserve missing evidence as a refusal or unresolved policy result. Return an immutable export reference or release-specific path, with any movable channel kept separate. Reuse completed output only for matching source pins, rights decision, fixed evaluation time and requested columns.

`ct-d8cf` owns the shared chronological comparison and runtime integration. This ticket owns the export decision and emitted bytes. Retain completed `ct-f11a` evidence as a link; `ct-jo8n` is the open predecessor.

## Acceptance Criteria

- Export the exact selected release and authorized column allowlist through the maintained caller. Preserve nested values, permitted metadata and identifiers; strip private field metadata, credentials, restricted payloads and expired content, including derived copies. Public authorization comes from the policy decision. Resolve required policy evidence from the release even for subset reads, and refuse absent evidence rather than inferring permission.
- Independently decode actual emitted output from both the callable versions-only path and the normal CLI. Cover restricted, metadata-only and redistributable records, expired referenced captures, missing capture evidence and permitted nested fields. Verify the approved authorized path. Compare the intended C5 behavior with the previous Python policy on valid inputs before removing duplicate production enforcement.
- Verify expiry immediately before, at and after `retain_until`, including mixed fractional precision. Expiry begins only when `now` is later than `retain_until`. Compare UTC instants while preserving source values and precision; do not rely on timestamp string order.
- An older export remains readable under its immutable reference after a later export to the same channel or destination. After a lost response, replay with the same release, policy inputs, fixed evaluation time and columns returns completed output without rewriting it. Reuse direct exports for unchanged allowed data without materializing the entire release in Python.
- Preserve archive and viewer ownership of routed assets and review bindings. Keep whole-group export optional for incremental updates. Retain focused failure results and independent review here; share applicable runtime and comparison evidence with the existing owners.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).

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

**2026-10-21T02:20:25Z**

Implemented and verified: wired news_lake.analysis.export.export_release(..., docspec_views=...) to DocSpecNewsViews.export_authorized, automatically binding release_read['dataset_pins'] from DocSpecLake.read_release so unchanged C5 tables export directly from their pinned ReleasePin without re-staging.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch mi03a).
- Grades: proposal 82 → 78, work 75 → 75.
- Problem: The whole release corpus must be in Python (`release_read['tables']`, export.py:85-92, 108), which is O(corpus) per export.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03a/mi03a-verdicts.md:17
- Status: Reopened: revisit under engine-first rule. C5 export rights are implemented twice (Python `export_release` and native `build_c5_export_policy`) with no parity check. WS8 (ct-d8cf) makes the engine policy the single authority (expiry as a native predicate, not an id list) and deletes the Python copy after a differential test that includes `retain_until == now`.
- See docs/reviews/2026-10-24-ticket-audit/README.md

**2026-11-05T17:11:15Z**

Current ownership after ct-mi03/ct-a1aa retirement: one News Lake rights/expiry gate, dependent one-way on ct-jo8n's exact-release selection. Carry the C5 portions of ct-5yof and ct-a3le: explicit release pins, column allowlisting and nested data, credential stripping, restricted/metadata-only cases, capture expiry for versions-only requests, retain_until == now, independent decoding, older export readback and lost-response replay. Use the native policy as the single production authority after the differential comparison; preserve failure-path tests and independent review. Parent is ct-d8cf; this parked work is not a Phase 2 exit condition.

**2026-11-05T20:56:46Z**

Final root-cause review: bind subset export policy to pinned captures, use chronological expiry, and retain immutable export references. Removed closed ct-f11a from hard dependencies while preserving its evidence link.

**2026-11-08T17:24:00Z**

2026-11-08 sweep-d: KEEP OPEN (parked; nothing exports publicly). Still in code: storage/docspec/export.py derives expired_capture_ids only from release_read['tables']['news.captures'], so a versions-only read gets an empty expiry set, and falls back to try_latest when a pin is missing. Recommended plainer A/C: refuse a subset export when the release's capture evidence is absent; expiry checked before/at/after retain_until with mixed fractional precision; write to a release-specific path. Defer the differential comparison and replay ceremony until export ships.
