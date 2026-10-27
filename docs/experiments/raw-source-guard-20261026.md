# Raw source qualification guard repair — October 26, 2026

Ordinary seed and code updates now use the daily incremental path without manual qualification. Changed seeds refresh related source metadata; absent seeds preserve retained documents. Explicit full replay remains available for intentional historical reinterpretation. The format, source/document reference, schema, and concurrent-writer checks remain. The original daily failures were caused by a seed digest gate, not PyArrow drift.

## Verified cause and live selection

[October 26 run](https://github.com/civictechdc/congressional-tech/actions/runs/40297640461) and [October 25 run](https://github.com/civictechdc/congressional-tech/actions/runs/40177235940) both used code `c466a45e09e27bde48ade12454f8b458c3643d21` and seed revision `b1d1a008b97e0e7e4dfe354fe7f7a8c45ae70ae3`. The October 26 log and downloaded artifact confirm an `update` operation failed at the guard before source interpretation or catalog publication. The artifact contains no accepted source-update preparation.

Three read-only R2 GETs established the current selection. See [machine evidence](raw-source-guard-20261026.json) for exact keys, ETags, byte sizes, and digests. Its catalog selector SHA-256 is `1bd6a77471c5a07ddfe1607fbfd801b7255ae18b6ab271bc69e1c26b20acebc4`; selected metadata SHA-256 is `97e2ff1b675d11ba2dc6f4c9a9e25182474fa47060bc48b7913b358ffde841b8`. It contains **1,683,430 source rows and 1,241,157 grouped documents**. The raw selector SHA-256 is `4773ba6bcf55404cfbbb01242df8e25c931e5e5454ae2e5072ce23addc4afcd6`, matching the contribution's raw identity. The selected catalog matches the retained October 24 qualification receipt.

All five `source_update_requirements()` fields match the selected contribution at the base revision:

| Field | Selected and current base value |
| --- | --- |
| `implementation_sha256` | `99d332dee404baaaa714aa9cc0e16a7ca83215351ce4d30d907d42410683d5aa` |
| `format` | `retained-source-update-v1` |
| `pyarrow` | `25.0.1` |
| `source_policy_sha256` | `5aa30187c8bd7b0a0be3cd9e7abdcbcd092f6d6905333fc0bdacc12873e33551` |
| `filename_rules_sha256` | `db8498f7f9623dd81737da20980abd76d69f26e1b69f35dcd1e340f70b51acd5` |

Only `seed_sha256` differs:

| Input | Exact interpreted seed digest | Link count |
| --- | --- | ---: |
| Selected contribution / retained qualification seeds | `1e2b82c48062fb265c1d11993e700f89d0092f85942cb0a807973454a273e39b` | 300,282 |
| Both failed runs | `83aaca9ba72dbb261b6d63ebf30d1ba740be43c67d89f62c02960acf8443c4f4` | 300,307 |

The digests were recomputed through the maintained `seed_files()` interpretation and exact ordered canonical JSON hash used by `retain_source_seeds()`. Only `congress_meetings.jsonl.gz` changed: compressed-file SHA-256 `07586a9e415b3f0e6a3478f6a3167d21e16d42129897425e7fad0997a5ff85cf` → `4babe767ea05e072734aaf51d1c6fb591fc14bc1e441c324dd6a673a6bf6f1e5`. GPO, House inventory, and Senate inventory bytes match; `house-sites.json.gz` is absent in both. Net 25 links does not establish 25 new grouped documents. Retained inputs and source bodies remain untouched.

## Simplified update behavior

Seed and implementation fingerprints remain in each update's before/after metadata for provenance and exact retry checks. A changed fingerprint no longer forces global qualification. Incompatible source-contribution formats still refuse before publication.

A seed-only change now reaches the maintained replay path even when the raw capture selection is unchanged. Seed URL and meeting dependencies select the related retained receipt inputs for replay, so corrected metadata reaches saved documents. New hints add documents; removing a hint does not delete previously retained source evidence. Unrelated components keep their values and exact references. This uses existing dependency replay and grouping rather than adding a separate import or migration path.

CLI operation identities now include raw selection, seed file digests, mode, and current implementation requirements. Different seed/code snapshots get separate continuation directories. Exact retries reuse their completed work, and conflicting continuation inputs still refuse. This prevents a second daily seed refresh from colliding with the previous operation when captures have not changed.

The earlier qualification repair remains: production no longer copies selected tables into its observed output and compares them with themselves. It checks freshly replayed values against the exact native selection when an operator explicitly requests qualification. Shape-only baseline caches and the hardcoded experiment-directory shortcut are removed.

## Operational effect

Once this local change is integrated and deployed, the existing workflow's `raw-source-sync --update-only` command accepts ordinary new seeds. There is no old-seed qualification followed by a named seed adoption step. Use `--upgrade-source-rules VERSION` only when intentionally reinterpreting the complete historical inventory, such as a global grouping/identity change or deliberate removal of old discovery hints. Initial adoption of an existing archive remains explicit.

New data uses current code while untouched historical rows retain their existing values. Code fingerprints record production history; they do not claim that untouched history has been recomputed by newer code. The approved runtime and dependency pins remain in the workflow.

A seed snapshot change processes the current seed list and its related receipt dependencies. This does not require a complete catalog scan, but it is not a measured claim that the work is proportional only to the number of changed links. No production runtime or full-corpus timing claim follows from the local fixtures.

No remote selector write, data qualification, upgrade, full rebuild, dispatch, deployment, or publication ran in this task. The original live identities above are diagnostic observations from October 26, not newly qualified production outputs.

## Verification

- New daily-update regressions initially failed at the seed gate. They pass under both test and production code paths after the change.
- Tests cover new links, corrected labels on retained receipt-backed documents, withdrawn seeds preserving retained documents, unchanged raw input, unrelated component preservation, and retry-directory separation.
- Tests cover code, policy, filename-rule, and runtime fingerprint changes accepting ordinary updates while leaving unrelated historical components intact.
- The incompatible-format, broken-reference, source-deletion proof, exact-retry, and deliberate historical-reinterpretation tests remain.
- The earlier qualification false-pass regression rejects an unreplayed fact before publication, and positive qualification and stale-baseline controls pass.
- Final focused suite: **107 passed in 78.63 seconds**, including real native fixtures, across raw updates, CLI modes, source-update proof, source replay, and workflow argument execution. The augmented code-change retry check also passed. Native fixtures use temporary local workspaces; the maintained offline wrapper disables external network access. `git diff --check` passed.

The maintained operational instructions are in `.github/workflows/raw-source-tables.md`. Viewer publication/capacity, GPO/YouTube collectors, news-lake imports, and redesign documents remain outside this change.
