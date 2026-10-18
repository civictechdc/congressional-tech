# Process efficiency merge review — 18 October 2026

**Verdict: APPROVE after two corrections.** Three independent reviewers examined
catalog/data integrity, publication/restart behavior, and the development/CI
environment. The integrating reviewer examined compression, browser measurement,
status reporting, supporting evidence, and the corrections. This review covers
`24137dd08241c34f1632afcd78a80a6138e5779d..be516559884c26477ccfdf21afd7dbfd086fde6c`
plus the corrections committed with this report. No remaining merge blocker was
identified. This approves local integration; hosted execution and full-catalog
viewer qualification remain separate.

## Resolved findings

| Finding | Correction and verification |
| --- | --- |
| P2: a Python-pin-only PR would skip validation | Added `.python-version` to `.github/workflows/validate-explorer.yml` PR paths. `.github/tests/test_dev_environment.py:16` verifies runtime/dependency/lane pin coverage. The environment reviewer independently rechecked the fix. |
| P2: explicit recovery acceptance could be saved before prepared files were validated | `apps/site/scripts/publish-viewer-r2.py:235` now builds the verified index before the accepted-object write, then passes it to selection to avoid a second scan. `tests/test_filename_recoveries.py:140` checks missing filenames and same-size corrupt groups, with every write forbidden. The publication reviewer independently rechecked the fix. |

The publication review also identified an overstated comment: recovery resume
requires equal decoded manifest values and binds the current remote byte digest;
it does not compare the original remote encoding with the canonical local copy.
The comment now describes that behavior accurately. Table hashes and prepared
values remain fixed; this correction changes no execution behavior.

## Implementation and verification trace

| Path | Inputs and processing | Result and checked boundary |
| --- | --- | --- |
| `scripts/dev.py:73`, shared setup action, root lock | Exact Python pin, six local workspace members, explicit test lanes and native tools | Preflight rejects wrong interpreter/import/dependency/tool state; test inventory exposes omissions. Lock audit found no Congress API version changes or same-version artifact URL/hash/size changes. |
| `retention/catalog_publication.py`, `derived_files.py`, `catalog_staging.py`, `r2.py` | Selected catalog identity and streamed owned files | Table digests, metadata, lifetime, version checks, conditional history/generation/selection and narrow derived-key writes were traced through maintained consumers. No blocker found. |
| `retention/document_index.py`, `raw_catalog.py` | Retained occurrences plus legacy filter values | One-pass source context preserves pairing, output order and required metadata. Independent evidence checks cover 48 D/F output tables and retained history bytes. |
| `apps/site/scripts/publish-filename-viewer.py:109` | Verified source Parquet and explicit Zstandard policy | Repack retains exact schema metadata and ordered batch values. Default is level 9; derived output, IDs and review binding remain checked. |
| `scripts/viewer_publication_attempt.py:37,104,153` | Source/accepted/viewer identities, prepared inventory, artifact custody and original attempt | Preparation precedes publication; explicit resume restores and reconciles original outputs/conditions. Complete inventory includes every ID shard. |
| `scripts/recovery_publication_continuation.py`, `guarded_recovery_publication_client.py` | Durable write intents and conditional requests | Journal chain, nonce, exact body readback and process/client-specific transfer proof prevent blind retries and unverified reuse. Public selection follows fresh protected-input checks. |
| `scripts/benchmark_viewer_browser.mjs`, `viewer_benchmark_server.py`, `benchmark_viewer_publication.py` | Verified local files, pinned reviews/recoveries/cases, real maintained loaders | Cross-origin Chromium uses exact byte ranges. Comparison requires matching input/runtime/result identities before per-case latency evaluation. Full-scale qualification stays explicit. |
| `scripts/pipeline_status.py:164` | Bound GitHub run, bounded heartbeat and optional local receipts | Run/attempt/revision and monotonicity checks distinguish recorded outputs from current public verification; the command never resumes or publishes work. |

Retained source evidence remains authoritative. Catalog optimization does not grant
body writes. Conditional pointer writes do not constitute a transaction across
multiple mutable objects. A complete local receipt does not prove current public
selection. These distinctions were checked in callers, error paths, assertions
and operator documentation.

## Test and evidence results

After both executable corrections, the integrating reviewer ran:

```sh
.venv/bin/python .github/scripts/offline-python.py -m pytest -q \
  .github/tests/test_dev_environment.py tests/test_filename_recoveries.py \
  tests/test_viewer_benchmark.py tests/test_viewer_benchmark_server.py \
  tests/test_pipeline_status.py .github/tests/test_viewer_r2.py \
  tests/test_recovery_viewer_transfers.py tests/test_viewer_publication_attempt.py \
  tests/test_recovery_publication_continuation.py .github/tests/test_filename_publication.py
```

Result: **130 passed, 2 subtests passed in 26.87 seconds**. The subsequent source
change only corrected the manifest comment. `git diff --check` passed.

Previously completed integration at `5b128da` passed 8,838 production-offline,
241 experiment, 49 native-loopback, 113 explorer and 7 viewer-data tests, plus type
checks and a 29-page build. The only changes from that revision through `be51655`
were documentation/evidence. Those full suites were not repeated for the narrow
review corrections. The 19 retained integration files were independently checked
against their recorded lengths and digests. Catalog reviewers additionally checked
61 compressed D/F reports/logs against retained originals and the frozen sources.

The saved three-arm browser fixture contains 12 cases × 5 repetitions × 3 levels
(180 samples), with identical per-case result hashes across levels 19/9/3. Its full
receipt digest was checked against the compact record. This verifies the harness
and fixture; the failed full Linux viewer attempt remains unqualified and retained.

## Limits and retained review details

Hosted artifact custody, hosted Node 22, complete Linux native execution and
representative remote publication latency were not newly exercised. The full
viewer memory failure remains unresolved; file-backed catalog I/O does not prove
it fixed that separate path. No full rebuild, held-out classification, source
acquisition, production publication or automatic retry was performed for this
review.

Detailed reviewer traces, hypotheses, inspected-file inventories and evidence
audits remain under `output/merge-review-20261018/` in the preserved
`/Users/mikewolfd/.codex/worktrees/process-efficiency/congressional-tech` worktree.
The two identified regressions were corrected and rechecked before integration.
