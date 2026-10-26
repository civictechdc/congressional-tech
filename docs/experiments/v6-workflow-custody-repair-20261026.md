# Interrupted filename preparation and Pages verification

The local repair saves a controlled preparation interruption as an explicitly
incomplete artifact, verifies that artifact before resuming, and requires the
real filename worker to pass before and after a Pages deployment. It does not
publish data or deploy the site.

Base revision: `c466a45e09e27bde48ade12454f8b458c3643d21`.
Worktree: `/Users/mikewolfd/.codex/worktrees/preparation-artifact-custody/congressional-tech`.
The final task report records the local commit SHA.

## Why work was lost

The preparation step could consume the entire 180-minute job limit. Its normal
artifact upload accepted only complete preparation. The final diagnostic upload
retained receipts but omitted the renderer's working files, SQLite database,
journals and partial outputs. A hard job timeout could therefore discard all
usable preparation work. An `always()` condition cannot guarantee recovery after
the enclosing job has stopped.

## What changes

The existing standard-library bootstrap now also supervises preparation. At
130 elapsed job minutes, measured from the first job step, it sends `SIGINT` to
the preparation process group and allows 120 seconds to unwind. It refuses
checkpoint acceptance if forced termination is needed or descendants remain.
Only the supervisor emits preparation step outputs; the child cannot leave a
stale `prepared` output authorizing publication.

After a graceful stop, the supervisor hashes every saved file and records the
original continuation binding in `workflow-checkpoint.json`. The workflow
uploads the entire `viewer-preparation/` tree, including hidden files, sibling
renderer state, SQLite journals and partial files, in a regular step. It then
records the uploaded artifact's exact selection and fails the run to require an
explicit new dispatch. The remaining job budget is a margin for hashing and
upload, not a measured guarantee for arbitrary artifact sizes.

Checkpoint artifact names use
`viewer-preparation-checkpoint-<producer-run>-<producer-attempt>-<receipt-sha256>`.
The version 2 descriptor has `kind: preparation_checkpoint`. Its `run_id` and
`run_attempt` identify that artifact's producer; `original_run_id` and
`original_run_attempt` identify the original preparation. `revision` identifies
the effective code checkout, and `workflow_revision` records the producing
workflow head. Version 1 accepted-publication descriptors remain unchanged.

Admission requires an explicit workflow dispatch, the same repository and the
original code revision. For preparation resume, `GITHUB_SHA` must equal the
descriptor's `revision` before checkout or workspace setup. Dispatch using an
existing branch or tag at that revision. If none exists, this conservative
policy cannot resume until a suitable ref is deliberately made available.
This avoids producing a new accepted artifact whose code revision differs from
the `run.head_sha` used by existing version 1 discovery. Accepted-publication
resume still selects its original revision as before.

On restore, the supervisor rechecks GitHub run and artifact metadata, producer
identity, revision, artifact digest, expiration, receipt digest, original input
binding, exact file set and every saved byte. Checkpoints containing publication
writes are refused. A checkpoint is preparation-only: the general descriptor
parser rejects version 2 unless its caller explicitly allows preparation, so
`publish --resume-descriptor` rejects it before client creation.

The workflow still requires complete preparation verification and a newly
accepted artifact before publication. An incomplete checkpoint never enters
that path. The existing accepted-artifact resume path and unchanged preflight
skip remain.

## Runtime integration requirements

The separate runtime repair must provide these behaviors before this workflow
can resume real initial preparation:

- Accept `prepare --resume-preparation` without requiring `--renderer-upgrade`.
  The supervisor passes the existing native configuration and the current
  `GITHUB_RUN_ID`/`GITHUB_RUN_ATTEMPT`; it does not substitute old producer IDs.
- Before using saved work, freshly compare code/runtime, native execution
  configuration, selected source, viewer and accepted-recovery control records
  with the original continuation binding. Workflow artifact verification proves
  saved-byte custody, not current remote input validity.
- Retain the original preparation identity during incomplete work. Once complete,
  produce accepted preparation under the current run and attempt. An already
  accepted publication resumed through version 1 retains its existing identity.
- Keep all durable state inside `viewer-preparation/`, including the existing
  `publication.renderer-upgrade/` sibling directory. On `SIGINT`, close database
  writers and leave only committed reusable units. The supervisor never accepts
  work while a child process can still modify it.
- Continue to run complete output verification after resumption. A saved partial
  inventory does not establish semantic completion.

No runtime files owned by the sibling task were edited here.

## Pages deployment checks

The build job serves its actual Astro output under the configured
`/congressional-tech/` base and runs `verify-live-publication.mjs` against the
real public filename selection. The existing verifier executes the built page
and worker in Chromium. The new strict option requires a selected v6 manifest
and a `passed` worker result; `pending`, failed and older selections fail.
Only after that gate can the Pages artifact upload and deployment proceed.

The deploy job runs the same verifier against the actual deployment URL and
requires the complete pointer to equal the built-site observation. A concurrent
selection change fails verification rather than silently qualifying different
data. Success and failure receipts are retained. A post-deployment failure marks
the workflow failed; it does not roll back the deployment.

The browser action installs exact `playwright@1.64.1` and matching headless
Chromium. It follows the maintained
[Playwright CI browser installation procedure](https://playwright.dev/docs/ci).
Site dependency and lock files remain unchanged.

## Evidence and limits

- **124 Python checks passed** across workflow admission, checkpoint custody,
  Pages workflow wiring, publication CLI, and existing accepted-publication
  attempt tests. The real subprocess test creates SQLite work, interrupts it,
  archives and restores it, interrupts a second resumed producer, verifies its
  new artifact/original preparation identities, then completes under a third
  producer. Separate cases reject forced stops, ordinary command failure,
  changed artifact/run/revision, altered bytes, missing/extra files, symlinks,
  publication writes and version 2 publication descriptors.
- **21 maintained JavaScript verifier checks passed** using Node `22.22.2`.
  The shell helper passes `bash -n`; changed files pass `git diff --check`.
- A read-only real-browser check of the deployed dashboard failed with
  `page.evaluate: Error: Unsupported filename catalog version.` Its failure
  receipt is `/tmp/ct-workflow-worker-deployed-observation.json`. This confirms
  the new gate catches the current deployment issue. It is not production
  success proof.
- Python checks used `3.12.9` with test-only `ijson==3.6.0` and
  `zstandard==0.25.0` installed under `/tmp`; the locked workflow requests
  `3.12.13`. An unrelated installed Pydantic/Logfire plugin emitted one warning.
  The live check used pinned Playwright `1.64.1` with installed Chrome, not the
  CI action's downloaded Chromium. Hosted runtime qualification remains pending.
- No hosted workflow was dispatched, no current clean Pages build was qualified,
  and no real v6 preparation was completed. The runtime sibling repair and a
  newly selected verified v6 publication must precede a passing deployment gate.
  Unplanned runner loss or a process that cannot stop within the grace period
  remains outside checkpoint acceptance; no automatic retry was added.
- The primary checkout and its unrelated diagnostic/design documents were
  preserved. No push, PR, merge, remote pointer change, job restart, publication
  or deployment occurred.

Changed files:

- `.github/actions/setup-publication-browser/action.yml`
- `.github/scripts/verify-built-filename-worker.sh`
- `.github/tests/test_pages_dependencies.py`
- `.github/workflows/deploy-pages.yml`
- `.github/workflows/publish-filename-viewer.yml`
- `apps/site/scripts/verify-live-publication.mjs`
- `apps/site/scripts/verify-live-publication.test.mjs`
- `packages/viewer_publication/src/viewer_publication/resume.py`
- `scripts/publication/prepare_workflow_resume.py`
- `scripts/publication/tests/test_preparation_checkpoint.py`
- `scripts/publication/tests/test_workflow_resume.py`
- `docs/experiments/v6-workflow-custody-repair-20261026.md`

## Follow-up: completion boundary and diagnostic stops

Integration review identified a race between completing the accepted receipt and
the supervisor's stop signal. After the process group is quiescent, the supervisor
now sends any complete receipt/result pair through the maintained `verify-prepared`
command, with a 20-minute verification bound inside the remaining job margin. A
valid pair for the current producer returns `prepared` for ordinary accepted-artifact
upload, even when the child exits zero at the deadline or an interrupt overwrites
its outer report. A process disappearing between timeout and signal is handled.
Failed verification or a different producer identity refuses acceptance; complete
pairs cannot be saved or restored through a version 2 checkpoint.

Before renderer initialization, a bounded stop is diagnostic-only and emits no
resume descriptor. Incomplete checkpoints require retained `stages.sqlite`, unless
the existing accepted `prepared` phase already permits receipt/result completion
without rendering. The runtime still verifies state contents and original inputs
when resuming.

The standard-library saved-state/receipt reader now permits 128 MiB, matching the
capacity repair's continuation limit. The checkpoint file bound permits 131,072
publication files plus 1,024 auxiliary files. A regression reads a 33 MiB binding
that the previous 32 MiB reader would reject.

The publication workflow now runs the workflow-resume and checkpoint tests before
preparation/publication. An explicitly accepted historical revision may predate
those two tests; only those absent tests are omitted on that version 1 route.
Current preparation treats missing checks as failures.

Follow-up checks cover real subprocess completion at interruption with exit codes
zero and 130, the timeout/signal disappearance race, failed complete verification,
old producer custody, pre-renderer stops, refusal of complete version 2 state,
accepted-phase continuation without renderer state, capacity bounds and actual
workflow shell selection. The subprocess CLI is a focused fixture; these cases
prove supervisor decisions, while the maintained publication attempt suite checks
the complete preparation verifier. They do not establish hosted runtime success.

Final follow-up result: **127 checks passed in 23.31 seconds** across
`test_workflow_resume.py`, `test_preparation_checkpoint.py`,
`test_publication_cli.py` and `test_viewer_publication_attempt.py`.
The same unrelated installed Pydantic/Logfire warning remained. The focused
workflow/checkpoint subset also passed all 58 checks; `git diff --check` passed.
