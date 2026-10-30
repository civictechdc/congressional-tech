---
id: ct-r6xw
status: closed
deps: [ct-70kc, ct-qqk2]
links: [ct-4fcl, ct-0bce, ct-fsbf, ct-8od2, ct-q29c, ct-3ttc, ct-unv0, ct-wxhg, ct-jufk, ct-gi01, ct-u7gg]
created: 2026-10-24T18:15:54Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-98sm
---
# WS10: delete shims and legacy formats

Compatibility shims and legacy formats from the Oct 20-24 refactors keep old tests' monkeypatching alive (audit syem hotspots 5 and 6, czsd hotspot 3).

First move: point the 42 monkeypatch calls on shim and publisher modules at the owning modules, or better at behavioral seams; then retarget the shims' importers (`retention/docspec.py` alone has 8 production importers).

Then delete: `retention/document_index.py` (`_CompatibilityShim`, after WS4); `retention/docspec.py` and `docspec_host.py`; `docspec_client/docspec.py` and `docspec_host.py`; the 7 `scripts/publication/*.py` wrappers (workflows call `python -m viewer_publication…`); `tests/historical_viewer_publication.py`; ct-8od2's unwired compaction helpers; the weekly retention mirror (ct-q29c) and its `update-data.yml` step; the `--streamed-recovery` flag; the in-process proof registries; `verify-live-publication.mjs`'s acceptance of manifest versions 2 and 5.

## Acceptance Criteria

- The monkeypatch retargeting lands before any shim is deleted.
- Before the weekly mirror goes, a check shows nothing reads the weekly datasets.
- Before the proof registries go, the re-hash cost on the real 1.09 GB catalog pair is measured.
- The legacy raw-table readers (`LEGACY_CAPTURE_SCHEMA`, `LEGACY_STATE_SCHEMA`) stay; `tests/historical_raw_archive.py` goes only if no surviving test needs a legacy raw fixture.
- R-check 1-2 pass, plus check 3 when imports in `raw_schemas` or `raw_storage` change.


## Notes

**2026-10-24T18:47:54Z**

Add: merge the two drifting copies of SourceModel and the YouTube models created when ct-ne06 broke the circular import (one shared module).

**2026-10-30T17:43:04Z**

Completed across df1bed37 (G02), c25ee9bb (G03), 9b387f85 (G13), 1e780f1e (G06), and 176cd4a1: deleted retention/document_index.py, retention/docspec.py, retention/docspec_host.py, docspec_client/docspec.py, docspec_client/docspec_host.py, tests/historical_viewer_publication.py, tests/historical_raw_archive.py, compact_readings.py, compact_reviews.py, streamed_recovery.py, and scripts/publication/*.py wrappers.
