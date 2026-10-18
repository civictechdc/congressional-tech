# Apply conversion budgets only to conversions that run

Hosted publisher run `39169129734` refused during documents repacking on
2026-10-18 at 21:48 UTC. The reported single-row Python/JSON estimate was
167,939,288 bytes, above the unchanged 134,217,728-byte limit. Repacking writes
and compares Arrow values without converting them to Python. Applying that
estimate there rejected an operation it did not describe. No publication was
accepted.

`bounded_batches` now takes an explicit boolean `python_values`, defaulting to
`True`. Only the three Arrow-only repack streams pass `False`; arbitrary stage
names cannot disable admission. These streams skip estimator work and omit its
metric rather than recording a misleading zero. Actual Arrow limits, native
row planning, retained-buffer metrics, staging and full ordered equality remain
unchanged. No limit increases or dependencies are needed.

The complete production caller trace is:

| Caller | Calls | Value handling | Python admission |
| --- | ---: | --- | --- |
| `publish-filename-viewer.py` repack write | 1 | Arrow writer/staging | Explicitly disabled |
| Same file, source/output equality | 2 | Ordered Arrow slice equality, including schema metadata | Explicitly disabled |
| `filename_observations.py` build/verification | 2 | `to_pylist`, deterministic JSON | Default enabled |
| `filename_details.py` build/verification | 2 | `to_pylist` / per-row `as_py`, deterministic JSON hashes | Default enabled |
| `filename_alias_index.py` build | 1 | `to_pylist`, alias/index construction | Default enabled |

The standalone decoded-fixture runner also keeps default Python admission.
The 4 MiB ordinary Arrow, 16 MiB single-row Arrow, 32 MiB ordinary Python
estimate, 128 MiB single-row Python estimate and 32 MiB logical JSON limits are
unchanged. A later consumer can still refuse a true conversion over its limit.
This correction does not establish that the complete rebuilt catalog passes
those later stages. Native page/dictionary expansion and retained Arrow slices
remain outside any universal process-memory guarantee.

The regression writes one approximately 10 MiB Unicode Arrow row with nested
nulls, empty values, duplicates, order and schema metadata. Default Python
admission refuses its estimate above 128 MiB. Repacking succeeds while a patched
estimator raises on any call, proving that write and both equality streams stay
Arrow-only; an independent persisted-input/output comparison checks all values
and metadata. Separate tests keep the default 16 MiB Arrow refusal in both
modes, ordinary Arrow splitting, Python refusal and strict boolean selection.

The failure diagnostic artifact now includes only root/nested
`viewer-preparation/publication/**/preparation-memory-failure.json` receipts
from the publication output. Its `always()` step remains unconditional. The
workflow regression matches both receipt locations against the complete path
list and excludes partial Parquet, binary and manifest payloads.

Original evidence remains untouched under primary
`output/publication-remediation-20261018/rollout/`: the failure log, artifact ZIP
`12151991789` and its inspection receipt. The ZIP SHA-256 is
`1209b8773929035258a05204aa43f5087e148e2f006717431a3324c8e5a78b27`.
That artifact lacked the memory receipt, so the original error is supported by
the log rather than reconstructed receipt fields. Compact source references
and local check results are in
[evidence/stage-budget-correction.json](evidence/stage-budget-correction.json).

This implementation performed no real-catalog probe, acquisition, publication,
workflow dispatch, resource increase, push or merge. Any separate retained-data
qualification or production outcome must have its own receipt.
