---
id: ct-jo8n
status: open
deps: [ct-qkvr, ct-nloa, ct-5fkx]
links: [ct-nloa, ct-qkvr, ct-5fkx, ct-f11a, ct-4nyy, ct-gf8i, ct-n6lj, ct-csjp, ct-vt7i, ct-d8cf, ct-mi03]
created: 2026-10-20T22:15:53Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-d8cf
tags: [docspec, application-adoption, efficiency]
---

# Make News Lake reads agree on one exact published release

**Parked News Lake work.** The DocSpec CLI and named-release reader are delivered. The reader checks availability and exact table pins, including explicit empty inputs. The remaining gap is downstream: shared view state can substitute a newer bridge, and incremental handling assumes forward history. A retained October 24 probe also found an older available release unreadable after compaction; that result belongs to its stated runtime and needs qualification on the intended pin.

## Smallest useful change

Carry the available release's exact input pins and processor selections through bridges, joins, aggregates and reads. Reuse derived outputs only when their input and step dependencies match. Apply a proven forward delta; otherwise rebuild the required bridge from the selected inputs. Refuse missing or mismatched dependencies instead of falling back to a mutable latest version. Preserve application ownership of release availability, cursors, rights, historical mappings and explicit empties.

`ct-d8cf` owns writer fencing, recovery, rollback and maintenance integration. This ticket owns the exact-read result, including old-release readback after that maintenance. Share the same compaction scenario and evidence. `ct-4nyy` uses this exact release to authorize exports.

## Acceptance Criteria

- One fresh-process A/B/A read through the CLI returns A's exact values or refuses.
- An available old release stays readable after compaction (the same scenario as ct-d8cf).

## Notes

**2026-10-20T22:15:54Z**

2026-10-20 adoption review: packages/news_lake/src/news_lake/storage/docspec_backend.py (primary checkout). Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.

**2026-10-20T23:32:30Z**

Reopened by evolutionary-refactoring audit at `main` (`8221566d` / `33ce7877`):
1. `packages/news_lake` still has zero non-test callers of `docspec_backend.py`: `storage/coordinator.py`, `storage/releases.py`, `analysis/views.py`, and `analysis/export.py` never import or invoke `DocSpecLake`, `DocSpecNewsViews`, or `DocSpecClient`.
2. `DocSpecLake.committed` (`docspec_backend.py:951`) and `DocSpecNewsViews.pins` (`:1127`) remain ephemeral in-memory dicts; on fresh-process resume (`DocSpecNewsViews(client)`), `_pin` (`:1151-1156`), `_bridge_pin_for_refresh` (`:1168`), and `_base_version` (`:1279`) still fall back to `client.latest(dataset)` / `client.try_latest(dataset)` instead of reading durable release-pinned versions.
3. Multi-poll generation sealing across `Update`s is blocked by `ct-5fkx` (`UpdateSpec` ignores `spec['relationship']` at `docspec_backend.py:924-925`).

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A | Impl: D+ (Reopened). Zero non-test callers in packages/news_lake; DocSpecLake.committed (:951) and DocSpecNewsViews.pins (:1127) are ephemeral in-memory dicts that fall back to client.latest() on fresh-process resume.

**2026-10-21T02:20:25Z**

Implemented and verified: wired DocSpecLake.publish_release / read_release / find_release into news_lake.storage.releases (releases.py:183-196,290-310) and DocSpecNewsViews into news_lake.analysis.views (views.py:150-153,204-207) and news_lake.analysis.export (export.py:43-62). Added durable workspace state (.news_lake_committed.json, .news_lake_views.json, releases/<id>.json), explicit empty-table preservation across all 12 CONTENT_TABLES, and capture_inputs verification. Verified in test_published_release_lifecycle_fresh_process_resume_and_retire.

## Audit 2026-10-24

- Verdict: PARTIAL (batch mi03b).
- Grades: proposal 86 → 74, work 74 → 78.
- Problem: AC4: no tests for stale seal, changed dependency or lost publication response.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03b/mi03b-verdicts.md:18
- Status: Reopened. Unmet: AC3 (one release selector; native-latest fallbacks and `.news_lake_committed.json` remain), AC4 (stale seal, changed dependency and lost publication response are untested) and "the previous release stays usable" (automatic lifecycle compaction makes older releases unreadable). Owner: WS8 (ct-d8cf).
- See docs/reviews/2026-10-24-ticket-audit/README.md

**2026-11-05T20:56:46Z**

Final root-cause review: credit the delivered release reader; focus remaining work on exact derived inputs, A/B/A reads and old-release readback. Share maintenance evidence with ct-d8cf.

**2026-11-08T17:24:00Z**

2026-11-08 sweep-d: KEEP OPEN (parked). Still in code: views.py _bridge_pin_for_refresh (~:229) swaps in client.try_latest when it differs from the selected pin, and :238 falls back to try_latest. A/B/A and old-release-after-compaction cases remain unexecuted. Recommended plainer A/C: one fresh-process A/B/A read through the CLI returns A's exact values or refuses, and an available old release stays readable after lifecycle compaction (shared with ct-d8cf).

**2026-11-08T17:42:58Z**

2026-11-08: acceptance criteria simplified by owner decision (proposed by the ticket sweep); the earlier criteria are in git history.

**2026-11-11T14:41:33Z**

validated 2026-11-11, left open: parked News Lake work, nothing changed since the 2026-11-08 simplification (no commit names ct-jo8n; last packages/news_lake commit d4d53baa is ct-xu1o's).
