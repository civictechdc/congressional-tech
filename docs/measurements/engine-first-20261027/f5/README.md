# Switch deletion preparation

F5 now covers 18 congressional-tech groups. docspec-rs is outside this strip; its lifecycle and external consumers require a separate later audit. A CT file or function is a candidate only when a named engine-first replacement is live and its production callers have migrated. Each deletion commit must name that replacement and measure actual lines before and after. The generator deletes nothing.

The version3 inventory reads committed CT blobs, records hashes and `wc -l`, and indexes definitions, imports, calls and literal workflow references. It separates production callers from tests, fixtures, measurement scripts and documentation. Those evidence files do not keep obsolete production code alive: old-only cases go with their subject, while mixed files require a case split. Unknown receivers and dynamic imports remain explicit; a missing static reference does not prove absence. Every group records replacement paths and a live-replacement gate. The production import graph excludes test and measurement paths.

The raw writer, body store, provenance, shared custody and `derived_files.copy_checked`, weekly meeting tables, news_lake, committee explorer, called docspec_client paths, review binding APIs and canonical review data stay. The active publication pointer writer, `VerifiedTransfer`, namespace checks and their imports remain explicit keeps. Phase-2 PDF copying, receipt rewriting and review import gates remain visible. The retired v6 benchmark and its old-only tests are superseded by `apps/site/scripts/measure-archive.mjs`; the active target/browser harness and process-memory sampler stay.

The CT-only snapshot at `9030d537` has SHA-256 `e5c8331f851a28f964f7d8787fc9acdaae76022d617bcd2b07a07ed225ed8f82`: 609 files and 128,194 population lines, including 51,162 source, 74,619 test, 1,814 configuration and 599 document lines. Fixed-head regeneration is byte-identical and current verification reports no changed source paths, relevant uncommitted paths or generator changes. Nineteen focused checks pass on the refreshed source. The single code review's two findings were reproduced and fixed: canonical review keeps and replacement-path accuracy. This snapshot covers the raw branch; regenerate from the final combined head at the switch.

The earlier inventory `3df1f981` covered 19 groups and included engine files. It is historical and must not be used for the current strip. The selected JSON is `codex-raw/cxb_switch_deletions.json` in the protocol scratch directory; immutable prior selections remain under `run2/f5/`. Regenerate from the final combined CT head after all source changes land. Candidate population counts include shared and gated files and are not deletion estimates.

```sh
.venv/bin/python -I scripts/measure/cxb_switch_deletions.py \
  --ct "$PWD" --out "$RAW_SCRATCH/cxb_switch_deletions.next.json"
.venv/bin/python -I scripts/measure/cxb_switch_deletions.py \
  --ct "$PWD" --verify "$RAW_SCRATCH/cxb_switch_deletions.next.json"
```

An optional `--ds` records only a deferred source revision; it never scans engine files or adds engine cuts. Verification refuses old inventory versions, changed source hashes, changed generator bytes and relevant uncommitted changes. Before applying a group, resolve production imports, workflows, named planned consumers and external-consumer evidence; keep tests of surviving behavior and delete only obsolete-subject tests, fixtures and measurements. Actual deletions remain with the switch owner after deployment and accepted raw migration.
