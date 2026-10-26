# Shared tests and release identity: merged-source review

Reviewed main: `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`.

Local repair: `8a838bf5ee8bb6c62c6bc6cc8b45ff87ce76a0b7`.

Review date: 2026-10-26. Method: semi-formal code review with source traces, isolated-process import checks, bounded offline collection, and focused execution. This reviews the combined merged source in the assigned seams, including the current workflow test selection and updated publication checks; it is not a review of only the earlier test patch or every unrelated collector implementation.

## Findings first

### F1 — Missing implementation sources allow code-identity drift

Severity: **P1 / correctness / request changes on the reviewed main**. Fixed locally in the separate repair commit above.

At the reviewed main, `packages/viewer_publication/src/viewer_publication/release_identity.py:28-52` included the publisher wrapper scripts and the older `congress_api.retention.docspec` re-export, but omitted:

- `packages/viewer_publication/src/viewer_publication/publish_viewer_r2.py`;
- `packages/viewer_publication/src/viewer_publication/publish_filename_viewer.py`;
- `packages/viewer_publication/src/viewer_publication/constants.py`;
- the maintained Python implementation under `packages/docspec_client/src/docspec_client/`.

These are executed sources. `publish_viewer_r2.py:121-137` calculates the publication implementation identity and owns validation/upload behavior. `native.py:109` invokes the builder implemented at `publish_filename_viewer.py:166-178`. `publish_viewer_r2.py:19` and `publication_preflight.py:26` load publication constants. `attempt.py:77-81` obtains `NativeDatasets` through `congress_api/retention/docspec.py:7-29`, which re-exports the actual client and host through `packages/docspec_client/src/docspec_client/docspec.py:2-4`. Native execution-file bindings cover the binary/configuration inputs, not this Python implementation (`packages/docspec_client/src/docspec_client/client.py:299-302`).

**Practical consequence:** a change confined to these omitted sources can leave the implementation fingerprint unchanged. The preflight calculates that fingerprint at `scripts/publication_preflight.py:341-347`; preparation compares it with prior output at `attempt.py:64-72`; accepted-output verification relies on it at `attempt.py:217-218`. These checks therefore cannot detect that source change through their code identity. This is a reproducible identity gap, not a claim that production already selected an incorrect release.

**Executed reproduction:** all five representative files above were absent from the actual main inventory. In independent temporary roots, changing each file from `VALUE = 1` to `VALUE = 2` left `source_files` unchanged. Parameterized regression tests then failed on the five missing cases while the original identity-implementation and both import-order cases passed: **5 failed, 3 passed**. Log: `/tmp/ct-tests-review-source-before-ad222085.log`.

**Thin repair:** add the three maintained publication files to the existing explicit list and include the DocSpec Python package beside the other shared source-package trees. Preserve hashing, cache checks, wrapper compatibility, and publication behavior. Extend the existing mutation regression to these files (`packages/viewer_publication/tests/test_release_identity.py:41-59`). The fix adds four source-selection lines; it introduces no runtime compatibility path or new publication mechanism.

No other actionable defect was found in the assigned import, identity, CI-selection, or offline-collection seams. The full suite was collected, not executed.

## Rebase and preservation

Worktree: `/Users/mikewolfd/.codex/worktrees/news-lake-test-imports/congressional-tech`.

Branch: `codex/fix-news-lake-test-imports`.

Backup ref: `codex/backup-tests-before-main-ad222085`, preserving `5d40a2ebadf1f780a49d04cd756062f33216c4d7`.

The branch had no uncommitted work. It underwent the authorized empty rebase onto exact main `ad222085`; no earlier task commits were replayed. In particular, the old test-only workaround `6607c552` was not replayed: the merged `scripts/publication/tests/test_workflow_resume.py:155-160` still exercises the supported script import. The only source commit above the rebased main is the new F1 fix. The primary checkout and shared integration tree were untouched.

## Patch summary and exploration decisions

| Hypothesis | Result and evidence |
| --- | --- |
| Shared news-lake helpers remain independent of whichever `conftest` pytest most recently loaded. | Confirmed: a uniquely named support module supplies paths and `logical_state`; no bare `conftest` imports remained in `packages`, `tests`, `scripts`, or `.github` Python sources. Combined offline collection and 81 affected tests passed. |
| Script-first and package-first release identity imports expose the maintained functions. | Confirmed by reading the normal re-export at `scripts/viewer_release_identity.py:8-12` and executing both fresh-interpreter orders at `test_release_identity.py:15-38`. The empty placeholder is absent. |
| The code identity covers the maintained publisher and native client implementations. | Refuted at the reviewed main by F1; repaired and exercised with mutation tests. |
| Current CI selections include the new supervisor/capacity/local checks without silently omitting current files. | Confirmed: publication workflow lists them explicitly; only explicitly accepted historical resume may remove the four absent newer test files. Tests execute the actual selection shell for current and historical layouts. |
| The maintained offline lane can collect the combined merged test tree. | Confirmed before and after F1. Doctor verified interpreter, locked PyArrow, native prerequisites and each maintained import path before collection. |

The relevant combined changes retain the named news-lake support module, restore normal release-identity wrapper imports, include identity logic and local continuation in source hashing, and select the added workflow checks. F1 completes the missing maintained publisher/native-client coverage.

## Function trace

All source locators below are repository-relative. Except where explicitly marked as reviewed-main lines, they refer to repair commit `8a838bf5`.

| Function / entry | Source locator | Input → output | Verified behavior and next caller/callee |
| --- | --- | --- | --- |
| `fixture_records` / `batch` | `packages/news_lake/tests/conftest.py:21-28` | Named fixture path → parsed records / non-release records | Reads the same docs fixture at `news_lake_test_support.py:5-7`; assertions still require all record kinds in `test_contract_records.py:19-22`. |
| `logical_state` | `packages/news_lake/tests/news_lake_test_support.py:10-29` | Lake, control store, release IDs → comparable content state | Preserves table records, selected releases, cursor and availability; excludes warehouse-scoped snapshots. Recovery tests call it at `test_recovery.py:51`. |
| Script import | `scripts/viewer_release_identity.py:8-12` | Normal Python import → maintained function re-exports | Package-first does not pre-register an empty bare module; subprocess tests compare function object identity and returned inventories. |
| `source_files` | `packages/viewer_publication/src/viewer_publication/release_identity.py:20-71` | Repository root → relative-path/SHA-256 map | Selects source trees/files, checks file metadata before/after hashing, reuses only matching cache metadata, returns a copy. F1 changes selection at lines 31 and 41-43. |
| `runtime_fingerprint` | Same file, `:74-77` | Package versions, Python/platform → SHA-256 | Uses the same encoding for installed and locked environments. |
| `installed_runtime` / `locked_runtime` | Same file, `:80-105` | Installed distributions / root lock and Python pin → runtime fingerprint | Missing packages become `None`; ambiguous locked versions and a wrong Python pin refuse validation. Existing preflight regression covers equal fingerprints. |
| `release_source_files` / `implementation_identity` / `full_release_identity` | `packages/viewer_publication/src/viewer_publication/publish_viewer_r2.py:121-137` | Root/source map/runtime → release identity | Caller uses the same `source_files` implementation as preflight, then hashes its encoded map. |
| Preflight `main` | `scripts/publication_preflight.py:330-347` | Root → locked release identity for read-only checks | Imports through the script wrapper at line 35; fingerprint is calculated before constructing its remote reader. |
| `prepare` / `verify_prepared` | `packages/viewer_publication/src/viewer_publication/attempt.py:48-72`, `:214-218` | Current controls/code vs prior or accepted output → reuse/preparation/refusal | Current code identity enters `binding.code_runtime`; matching prior output can take unchanged path; mismatched accepted output is rejected. |
| `inventory` | `scripts/dev.py:53-72` | Tracked and untracked nonignored tests + lane roots → enrollment check | Rejects unassigned tests and absent roots; package directory enrollment covers the helper regressions without an ad hoc workflow-only path. |
| `doctor` | `scripts/dev.py:75-128` | Declared runtime/native prerequisites → fail or verified environment | Child imports must resolve inside this checkout; wrong interpreter/PyArrow or missing tools stop before pytest. |
| `test` | `scripts/dev.py:131-155` | Lane, permitted paths, pytest arguments → subprocess exit status | Runs inventory and doctor, validates selected paths, uses the offline wrapper and lane marker, invokes pytest with this root/configuration. |
| Offline wrappers / `main` | `.github/scripts/offline-python.py:18-70` | Socket/DNS calls and requested module → allowed loopback or refusal | Patches external connections and DNS in the current process, then executes pytest. It does not claim child-process network isolation. |
| Publication CI test-selection shell | `.github/workflows/publish-filename-viewer.yml:113-146` | Current/original checkout and accepted-resume flag → pytest file list | Current missing files still fail; historical flat paths resolve; only four absent newer files may be omitted for accepted historical publication resume. |

## Data flow and invariants

1. **Shared test data remains local to news-lake.** Fixture paths are derived from the named support module location. Callers import that unique name rather than a mutable global pytest configuration name. Recovery state semantics and assertions are unchanged (`news_lake_test_support.py:10-29`, `test_recovery.py:11-13`, `test_contract_records.py:16-27`).
2. **The wrapper and package share one implementation.** The wrapper imports the real module through Python's normal module cache. Neither test ordering nor package-first initialization can create an empty surrogate (`scripts/viewer_release_identity.py:8-12`, `test_release_identity.py:15-38`).
3. **Code identity binds executed maintained source.** `source_files` creates the digest map; the cache stores a metadata/map pair under the resolved root, returns copies, and invalidates on metadata/file-set changes. `full_release_identity` and preflight consume the same encoded map. F1 adds omitted execution code to that map. Nothing writes a remote object during hashing.
4. **CI cannot silently bypass current missing checks.** Current workflow selection enumerates the files and relies on pytest to reject missing paths. Historical omission requires `ACCEPTED_RESUME=true` and an exact four-file allowlist (`publish-filename-viewer.yml:139-144`); preparation checkpoints do not enable that branch. `test_workflow_resume.py:103-152` checks enrollment and executes the selection shell.
5. **Collection is different from execution.** `test-suites.toml` enrolls the relevant package/script roots in `production-offline`; the lane applies `not loopback`. Validation and meeting-refresh jobs both call this maintained lane (`validate-explorer.yml:56-60`, `update-data.yml:142-150`). CI setup syncs the lock and runs inventory/doctor (`setup-python-project/action.yml:18-28`).
6. **Offline is an in-process boundary.** Loopback remains available for local IPC; new child interpreters are not network-isolated by these Python monkeypatches. Both the lane declaration and wrapper document that limit. Review tests using fresh interpreters perform fixture/local-file work; their success does not prove a stronger network sandbox.

## Executed checks and boundary cases

Executed in the rebased worktree's `.venv` with Python 3.12.13 and local source imports. No full 11k-test execution was started.

### Exact reviewed-main collection

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/dev.py test production-offline -- --collect-only -p no:cacheprovider
```

At `ad222085`: **11,414 / 11,464 collected; 50 loopback cases deselected; no collection errors**, in 3.60 seconds. Log: `/tmp/ct-tests-review-ad222085-collection.log`. Inventory and doctor passed first, including checkout-location checks for maintained package imports.

### Regression proof before F1

After adding only the missing-source regression cases, the release-identity test file produced **5 failed, 3 passed**. Each failure was a missing inventory key. Same-size source mutations also independently returned unchanged inventories for all five representative omitted files. This established both missing enrollment and cache-visible behavioral impact before the repair.

### Focused combined offline execution after F1

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .github/scripts/offline-python.py -m pytest   -p no:cacheprovider --basetemp=/tmp/ct-tests-review-focused-ad222085 -q   packages/news_lake/tests/test_contract_records.py   packages/news_lake/tests/test_recovery.py   packages/viewer_publication/tests/test_release_identity.py   packages/viewer_publication/tests/test_viewer_publication_attempt.py   scripts/tests/test_publication_preflight.py   scripts/publication/tests/test_workflow_resume.py   .github/tests/test_dev_environment.py   .github/tests/test_viewer_r2.py
```

**258 passed, no skips**, in 43.25 seconds. Log: `/tmp/ct-tests-review-focused-ad222085.log`. The tested source/test changes were committed without further source edits as `8a838bf5`.

This exercised:

- script-first and package-first imports in isolated `-I -S` interpreters, shared function identity and equal inventories;
- same-size mutation of the identity implementation, both publisher implementations, publication constants and native-client/host implementations;
- unchanged-cache reuse, unchanged unrelated documentation, and changes with restored modification time (`test_publication_preflight.py:96-105`);
- fresh CLI bootstrap using package paths, actual shared identity functions and fixture-only refusal of unsupported source selection (`.github/tests/test_viewer_r2.py:21-67`);
- original workflow test's script import, current and historical workflow test path selection, invalid descriptor admission, and enrollment of capacity/local checks (`test_workflow_resume.py:33-180`);
- combined news-lake shape/docs/recovery checks, including per-fault-point convergence through the retained content comparison;
- prerequisite failures stopping before pytest and complete lane enrollment (`.github/tests/test_dev_environment.py:16-113`).

### Committed-fix collection

The same maintained collection command at `8a838bf5` produced **11,419 / 11,469 collected; 50 deselected; no errors**, in 5.62 seconds. The five additional cases are the new source-inventory regression parameters. Log: `/tmp/ct-tests-review-final-collection-8a838bf5.log`.

`git diff --check` passed. The report is committed separately from the fix.

## Limits and verdict

The parent's supplied integration logs also record 723 publication/workflow passes plus two subtests and 235 data passes; these logs were read as prior integration evidence and were not rerun here. They are separate from this review's executed checks. JavaScript, native transport qualification, production catalog preparation, artifact transfer, hosted CI, R2 publication and deployment were not rerun. No expensive full-catalog build or remote mutation occurred.

**Verdict on exact main `ad222085`: REQUEST CHANGES for F1.** The local repair closes the reproduced gap, and no other actionable regression was found in the assigned scope. Focused coverage of the repaired paths is adequate; confidence is high for those paths and bounded collection.

Root must integrate `8a838bf5` and qualify the final combined revision. Expanding source identity intentionally changes implementation fingerprints. Existing accepted preparations or checkpoints must retain their original-revision rules; these local results do not authorize treating old fingerprints as equivalent or claim a deployed repair.
