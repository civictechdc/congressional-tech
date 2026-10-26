# Raw source qualification guard repair — October 26, 2026

The daily raw catalog update correctly refused changed seed inputs. It did not fail because of PyArrow or source implementation drift. Local repairs now expose the mismatching fields and make the existing qualification route compare replayed values against the actual selected catalog.

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

## Local code repair

`catalog_raw_updates.py` now reports each changed requirement or seed field with its selected/current value while preserving the guard. It reuses the already calculated request requirements.

The production qualification path previously copied selected tables into its observed output and compared them with themselves. A second shortcut did the same when an observation-root cache existed. Both are removed. Qualification now runs the maintained interpretation path for both production and tests. Its selected baseline always comes from the exact selected native snapshot; matching schema and row count alone no longer admits cached tables or a hardcoded historical experiment directory. The continuation route for already completed exact source-update preparations remains intact.

This removes duplicate qualification paths and unverified cache reuse. It adds real replay/read cost to qualification; no speed claim or full-corpus runtime estimate follows. The old production-only behavior reproduced a false acceptance of a historical fact without a retained receipt. The regression now refuses before the catalog selector changes. Positive production-path coverage also preserves exact selected values.

## Prepared operational sequence — not executed

A data adoption operation is required. Changing a version label or turning off the guard would not adopt these inputs. `--qualify-sources` proves exact selected values; it cannot authorize new or changed values. `--upgrade-source-rules VERSION` deliberately applies the complete retained inventory and new seeds after a contribution has been qualified.

After the other current-pipeline fixes integrate:

1. Pin the **final integrated code SHA**, approved native runtime and PyArrow `25.0.1`. Recompute all five requirements and the ordered seed digest. This repair itself changes `implementation_sha256`; collector/parser fixes may change other fingerprints. A qualification from this isolated commit cannot qualify that later code.
2. Hold the maintained `raw-source-mirror` writer lock. Re-read and compare both exact raw/catalog selector identities above. If they differ, investigate and prepare new pins. Preserve source bodies, selected native versions, retained old seeds, and all old operation directories. Use a fresh retained operation directory tied to the final code SHA; never reuse the old October 24 directory under changed requirements.
3. Qualify the final code against the **old retained seed set**. The exact selected values must replay successfully. Investigate any mismatch; do not copy the selected output into the observed output. Because the former production shortcut could accept unreplayed facts, the old receipt alone is insufficient evidence of successful real replay.
4. If exact qualification passes, prepare an explicit named upgrade with the desired pinned new seed revision. Refresh the catalog pin from the qualification result before launching. Review additions/removals and ID mappings before downstream viewer publication. The current upgrade route may first evolve/publish a compatible raw state schema; it is an operational mutation, not a harmless version bump.
5. Only after successful adoption should the ordinary `--update-only` route resume. Future seed changes will require explicit adoption again under the current guard semantics.

The following commands are prepared for an approved **Linux runner**, with an explicit two-hour ceiling per attempt and existing native row/byte/memory limits. They are examples to execute only after the preconditions above. They scan the complete retained inventory; `--limit` and `--max-seconds` bound capture, not qualification. Two hours is a stop budget, not a completion estimate. Keep summaries, checkpoints, and partial evidence after a timeout, and inspect resumability before retrying.

Set `FINAL_SHA` to the final integrated commit, `DOCSPEC_RUNTIME_CONFIG` to its approved private runtime configuration with an owned workspace, and `RUN` to a new retained directory. Supply private R2 credentials through the existing runtime/runner mechanism; never put them in the command or report.

```bash
# In the final integrated checkout. These git reads do not contact publishers.
OLD_SEED_REV=2eb258199080c8f8de81cd78d6d62b6eb841e3e7
NEW_SEED_REV=b1d1a008b97e0e7e4dfe354fe7f7a8c45ae70ae3
RUN="output/raw-source-adoption-${FINAL_SHA}"
mkdir -p "$RUN/old/meeting-inventory" "$RUN/new/meeting-inventory"
for name in congress_meetings.jsonl.gz gpo-evidence.jsonl.gz \
  meeting-inventory/house.json.gz meeting-inventory/senate.json.gz; do
  git show "$OLD_SEED_REV:$name" > "$RUN/old/$name"
  git show "$NEW_SEED_REV:$name" > "$RUN/new/$name"
done

# First prove the existing values from their retained seed inputs.
timeout --signal=TERM --kill-after=60s 2h python -m congress_api.cli.raw_sync \
  --bucket congressional-tech-raw --native-config "$DOCSPEC_RUNTIME_CONFIG" \
  --index-workers 2 --qualify-sources \
  --catalog-directory "$RUN/qualify" --summary "$RUN/qualify-summary.json" \
  --seed "$RUN/old/congress_meetings.jsonl.gz" \
  --seed "$RUN/old/gpo-evidence.jsonl.gz" \
  --seed "$RUN/old/meeting-inventory/house.json.gz" \
  --seed "$RUN/old/meeting-inventory/senate.json.gz"

# Separate operation, only after exact qualification and review of new inputs.
timeout --signal=TERM --kill-after=60s 2h python -m congress_api.cli.raw_sync \
  --bucket congressional-tech-raw --native-config "$DOCSPEC_RUNTIME_CONFIG" \
  --index-workers 2 --upgrade-source-rules "meetings-seeds-b1d1a008-${FINAL_SHA}" \
  --catalog-directory "$RUN/upgrade" --summary "$RUN/upgrade-summary.json" \
  --seed "$RUN/new/congress_meetings.jsonl.gz" \
  --seed "$RUN/new/gpo-evidence.jsonl.gz" \
  --seed "$RUN/new/meeting-inventory/house.json.gz" \
  --seed "$RUN/new/meeting-inventory/senate.json.gz"
```

These mode/seed/directory arguments are covered by the focused CLI tests. Local fixture tests exercise exact qualification, refusal, explicit new-seed adoption, preserved unrelated values/IDs, and retries. No full raw rebuild, remote selector write, source qualification, upgrade, workflow dispatch, deployment, or publication ran in this task.

## Verification

- Red/green regression: the unchanged base accepted an unreplayed selected fact only when `PYTEST_CURRENT_TEST` was absent; the repaired production and test paths both reject it.
- Positive production-path fixture and same-shape stale-baseline controls pass.
- Four focused qualification/upgrade fixtures passed with the real local native executable and temporary workspaces. External sockets/DNS were disabled by the maintained offline wrapper. Native fixture limits: two compute threads, 512 MiB native memory, 256 MiB scratch, two rows per batch.
- Final focused suite: **57 passed in 94.55 seconds**, including real native fixtures, across `test_catalog_raw_updates.py`, `test_native_raw_cli.py`, `test_source_update_proof.py`, and `test_source_replay.py`. Both prepared operational invocations also parsed successfully without executing them. `git diff --check` passed. Production runtime and full-corpus data acceptance remain pending.

Changes are limited to this report, its metadata evidence, `catalog_raw_updates.py`, and its tests. Viewer publication/capacity, GPO/YouTube collectors, news-lake imports, and redesign documents are outside this commit.
