# Initial v6 preparation resume repair

The first v5-to-v6 preparation now uses `RendererState` through the maintained production prepare chain. Completed component chunks and source-route tasks survive interruption. Output still becomes an accepted preparation only through the existing inventory, recovery and receipt checks. This changes local preparation; it does not publish or select a release.

Base: `c466a45e09e27bde48ade12454f8b458c3643d21`.

Worktree: `/Users/mikewolfd/.codex/worktrees/initial-v6-resume/congressional-tech`.

## CLI and workflow interface

Start a fresh preparation:

```sh
python scripts/publication/publish-viewer-r2.py prepare \
  --native-config "$DOCSPEC_RUNTIME_CONFIG" \
  --directory viewer-preparation --report viewer-publication.json
```

Restore the entire verified checkpoint directory, check out its exact original `binding.provenance_revision`, recreate the exact native execution inputs, then resume:

```sh
python scripts/publication/publish-viewer-r2.py prepare \
  --native-config "$DOCSPEC_RUNTIME_CONFIG" \
  --directory viewer-preparation --report viewer-publication.json \
  --resume-preparation
```

`--run-id` and `--run-attempt` default to the current `GITHUB_RUN_ID` and `GITHUB_RUN_ATTEMPT`. A later run supplies its current identities, not the origin's. Initial adoption needs no `--renderer-upgrade`. An explicit upgrade of an existing v6 release still needs `--renderer-upgrade` on both invocations. Publication continues to use the separate accepted-publication resume interface. `publish --resume-descriptor` explicitly refuses version 2 preparation-checkpoint descriptors before constructing a client.

The workflow owns GitHub checkpoint-artifact authentication, the version 2 descriptor, bounded process-group interruption, artifact upload/download and full-tree file verification. No new receipt helper is required by this patch: origin and input pins remain in `continuation.json.binding`; completion identity remains in `prepared-result.json`; `verify-prepared` checks a completed preparation.

## Retained files and identity rules

Retain the whole directory after the process exits, including any SQLite journal and private partial files:

```text
viewer-preparation/
  continuation.json
  publication.renderer-upgrade/
    stages.sqlite
    stages.sqlite-journal       # only if present after abrupt loss
    ... private copy partials   # only if present
  publication/
    releases/...                # content-addressed output assets
    manifest.json               # once rendering completes
    recovery-prepared.json      # once recovery is accepted locally
  preparation-events.jsonl
  preparation-diagnostics.json
  preparation.json              # receipt may precede final result
  prepared-result.json          # complete accepted identity, verified before success
```

`publication.renderer-upgrade` keeps the existing directory name for both initial preparation and upgrades. Its SQLite `build`, `progress`, `assets` and `discarded` tables retain the binding, completed task identities, output sizes/hashes and deletion journal. Full synchronous transactions commit completed tasks; an interrupted task rolls back. Resume verifies retained assets before trusting completed tasks. Missing stages or changed/corrupt retained assets fail instead of starting again.

`continuation.json.binding` preserves origin `run_id`/`run_attempt`, exact source selector and version, prior viewer pointer, accepted recovery controls, code/runtime identity, publisher version, Git revision, native executable/configuration paths and byte identities, and full/recovery/upgrade mode. The renderer also binds source identity, rendering requirements, loaded review identities and the prior v5 review binding digest. A later invocation changes only the artifact producer identity; every non-run input must match. Native execution paths are currently exact bindings as well as their contents; the workflow must recreate those paths.

A completed `preparation.json` records `artifact_producer = {run_id, run_attempt}` separately from the origin binding. `prepared-result.json` names `viewer-prepared-<producer-run>-<producer-attempt>-<receipt-digest>` and its matching publication attempt. GitHub artifact custody checks the producer run. Existing version 1 accepted receipts without `artifact_producer` retain their origin-based behavior.

An interruption after the accepted `prepared` phase but before receipt/result completion reuses its verified inventory without rendering or recovery. An interrupted receipt without a result preserves its release plan and takes the current producer when completed. A complete receipt/result pair keeps its identity byte for byte, even if `prepare --resume-preparation` is invoked from another run. The workflow must then use the original accepted artifact rather than upload that identity under a different producer run.

## Progress and remaining limits

The CLI flushes JSON progress to stdout. `preparation-events.jsonl` appends closed task/stage records with UTC timestamps and elapsed seconds. `preparation-diagnostics.json` atomically records the latest event, invocation/origin, stage timings and existing decoded-data/resource counters. Stage timing reports cover the current invocation; earlier timings remain in the append log. These counters are admission estimates and data movement measurements, not a measured process heap bound. A hard exit leaves the last start/completion record available; a caught interrupt records the interrupted stage.

Events cover renderer stages/tasks, recovery indexing, renderer/preparation inventory, recovery acceptance, output validation, receipt/result creation, retained inventory verification and final accepted-preparation verification. No per-row logging was added.

Recovery indexing remains a whole stage. If it is interrupted, resume skips finished rendering and retries recovery indexing; it may read native data needed by recovery. Once the `prepared` phase is accepted, resume skips both. This patch does not introduce recovery-row checkpoints or alter recovery policy. Recovery-only publication retains its existing output behavior; the new retained renderer path targets full preparation and explicit rendering upgrades.

An interruption before renderer-state initialization can leave only an origin continuation and diagnostics. Such an artifact is diagnostic evidence, not a resumable renderer checkpoint: missing retained stages are rejected. The workflow should distinguish this from a checkpoint containing `stages.sqlite` rather than silently restart.

Initial control/catalog/native-input reads occur before the retained continuation is created. This patch does not add startup timing for those reads. It measures the costly rendering, recovery and acceptance chain after input admission.

## Local verification

The focused regression command covers initial-adoption chunk/leaf interruption, real CLI process loss using synthetic native tables, input/review/control drift, same-size retained-output corruption, v5 withdrawal preservation, later-run artifact identity, recovery/receipt/result interruption, accepted legacy receipts, CLI refusal and existing upgrade/copy-loss behavior:

```sh
DOCSPEC_BINARY=/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/docspec-remote \
uv run --frozen pytest \
  scripts/publication/tests/test_publication_cli.py \
  packages/viewer_publication/tests/test_filename_native_upgrade.py \
  packages/viewer_publication/tests/test_native_preparation.py \
  packages/viewer_publication/tests/test_filename_initial_resume.py \
  packages/viewer_publication/tests/test_viewer_publication_attempt.py -q
```

Final scoped result: **112 passed in 43.82 seconds, no skips**. `git diff --check` also passed. The parent located the existing qualified native executable at `/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/docspec-remote`. Four focused real-native cases passed: initial adoption and explicit upgrade, interrupted before and after a completed component chunk. They use private test workspaces, preserve the selected source and refuse native candidate creation while rendering. Synthetic subprocess tests additionally exercise complete CLI invocations and later-run acceptance. These are local fixtures; no production preparation, R2 publication, deployment or remote pointer change was performed.

## Integration ownership

This patch changes the preparation/state section of `filename_native.py`, not its schema/query indexes. It also changes the thin `publish_filename_viewer.py` wrapper to forward the new binding/resume arguments. The separate index and workflow repairs still need integration and their own verification. Restored checkpoints must use the final combined repair revision; pre-repair canceled runs cannot resume work that never retained renderer state.
