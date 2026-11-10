# Release 2026-11-10: procedure and state

Written by session congress-1 during the release window. To be folded into ticket ct-n5ec and
`docs/releases/` after the pointer moves (no commits to main during the window except step 4).

## Why this file exists

The 11-03 and 11-08 releases passed the release-cause gate by a hand procedure that was never
written down: their cause records were committed after publishing and no committed
`publish.json` ever carried a `release_causes` pin. This is the procedure used this time.

## Facts the procedure rests on (read at 8c3a3cae)

- The gate reads causes only through the publish spec's `release_causes` pin
  (`archive_publish_job.py:263`, `:557-559`; `release_gate.load_causes`). The record binds to one
  base and one candidate release id; every failing group needs exactly one entry with the gate's
  count; explained entries need evidence files pinned by path, sha256 and size
  (`release_gate.py:205-239`, `verdict` at `:404-425`).
- The publisher resumes a completed model when `archive-publish/completed-model.json` exists
  (`archive_publish_job.py:208-211`). Its resume checks do not include cause records, tickets,
  docs or `publish.json` (`archive_controller.py:113-121`, `:220-231`;
  `archive_model_profile.py:85-100`). They do include daily catalog heads
  (`archive_publish_job.py:188-196`): any raw or catalog write before the resume discards it.
- The nightly driver discards the candidate on any commit change (`scripts/nightly_publish.py`,
  the `Selected code commit changed` branch). So the resume is run by hand with the driver's own
  command. A driver change that keeps the candidate across a cause-record commit is on branch
  `claude/ct-cause-record-resume` (9d1a18f3), to land after this release.

## Steps

1. Build with the normal driver. Done: run `nightly/20261110T011925.309157Z`, commit 8c3a3cae,
   stopped at Gate 1 at 01:48:35Z, candidate a70ebc3d1466, base 630164505301, 96 failing groups.
2. Clone the candidate: `release-20261110/candidate-at-gate/` (done, before anything else).
3. Explain every failing group with evidence under `release-20261110/causes/<cluster>/`;
   independent cross-review; the owner reviews the list and approves.
4. One commit: `model/jobs/release-causes/630164505301-a70ebc3d1466.json` plus the
   `release_causes` pin in `model/jobs/publish.json`. Pushed on the owner's yes. Nothing else.
5. Resume by hand: detached checkout of that commit in `.claude/worktrees/nightly`, then the
   driver's publish command (`.venv/bin/python -I .github/scripts/run-archive-job.py publish
   --nightly-work <main>/.cache/archive-release/nightly/candidate`; inner argv recorded in
   `publish-watchdog.json` of the build run) with the environment `publish_env` builds
   (names: CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, DOCSPEC_RUNTIME_CONFIG,
   DOCSPEC_JOB_CONFIG, CONGRESS_TEXT_INDEX_WORK, ARCHIVE_DISK_BUDGETS, RUNNER_TEMP), under the
   driver's watchdog limits. Moving the pointer needs the owner's yes.
6. After the pointer moves: release note in `docs/releases/`, remove the `release_causes` pin
   (it is bound to this pair and would fail the next nightly), close tickets, land the driver
   change and the held branches.

## Window rules

From 01:19:24Z until the pointer moves: no pushes to origin/main except step 4, no raw writes,
no catalog head moves, no commits in the main checkout.

## Addendum 04:55Z: resume mechanics, read from e65aef7e (names only, no values)

- `publish_env` (`scripts/nightly_publish.py:102-120`) starts from the caller's environment, drops
  PYTHONPATH, VIRTUAL_ENV, DOCSPEC_JOB_CONFIG and DOCSPEC_RUNTIME_CONFIG, then sets:
  CLOUDFLARE_ACCOUNT_ID (parsed from `properties.s3.endpoint` in
  `<main>/.cache/archive-release/remote-runtime/remote.json`), R2_ACCESS_KEY_ID and
  R2_SECRET_ACCESS_KEY (keys DOCSPEC_S3_ACCESS_KEY_ID and DOCSPEC_S3_SECRET_ACCESS_KEY of
  `remote-runtime/credentials.json`), DOCSPEC_RUNTIME_CONFIG (`remote-runtime/runtime.json`),
  DOCSPEC_JOB_CONFIG (`<nightly worktree>/.cache/local-runtime/runtime.json`),
  CONGRESS_TEXT_INDEX_WORK (`<main>/.cache/archive-release/text-index/work`),
  ARCHIVE_DISK_BUDGETS (`<main>/.cache/archive-release/disk-budgets.json` unless already set),
  and RUNNER_TEMP (the run's evidence directory). No keychain is involved.
- The driver's publish step is `<nightly worktree>/.venv/bin/python -I
  .github/scripts/run-archive-job.py publish --nightly-work <main>/.cache/archive-release/nightly/candidate
  --nightly-lock-fd <fd>`, run with cwd = the nightly worktree. `run-archive-job.py` wraps the
  publisher in `scripts/archive_watchdog.py` with the limits bound in the job binding (see the
  `command` and limits recorded in the build run's `publish-watchdog.json`).
- Lock: `<main>/.cache/archive-release/nightly/lock`, taken with `fcntl.flock(LOCK_EX | LOCK_NB)`
  on a file opened in append mode and inherited by the child as a file descriptor
  (`nightly_publish.py:415-433`). `--nightly-lock-fd` must be that inherited descriptor.
- The driver also runs its setup steps (uv sync, npm ci, local runtime, doctor, spicy-regs, site
  build, clean-tree check) before publish on every run. A hand resume at a commit that changes
  only cause records, tickets and docs reuses the worktree's existing environment and site build.
- Accepted-defect entries name ticket ids; the ticket files go in the same commit as the record
  and the pin.

## What happened (added after the release)

- The first candidate of the night (a70ebc3d1466, built at 8c3a3cae) stopped at the gate with 96 groups.
  Review found six fused House Financial Services PDFs and a file-name swap; the owner chose to fix both
  first (ct-h3jb, ct-f7hp). The rebuilt candidate 619db5f9e08e (commit e65aef7e) stopped with 95 groups.
- Causes were written in five clusters and cross-reviewed; the working files are under
  `.cache/archive-release/release-20261110/` (`causes-2/`, `decisions-overnight.md`).
- Step 4 was commit 9e68416d (the record, the pin, tickets ct-u9y4 and ct-yuf0).
- Step 5 was run with `.cache/archive-release/release-20261110/resume_publish.py`, a wrapper that
  refuses unless only the record, the pin, tickets and docs changed since the build, then runs the
  driver's own publish command with the driver's environment, lock and process ownership. Published at
  2026-11-10T05:34:59Z; the run is `.cache/archive-release/nightly/20261110T053213.525969Z-resume/`.
- Step 6: the pin was removed in 0fad483d.

## Next time

The nightly driver now keeps a candidate whose only changes since the build are cause records, the
`release_causes` pin, tickets and docs (`only_cause_records` in `scripts/nightly_publish.py`). So after
a gate stop: write and review the record, commit it with the pin, push, and run the nightly again; it
resumes the same candidate. Remove the pin in the commit after the pointer moves. No raw or catalog
write may happen between the build and the resume: the publisher refuses a candidate whose daily heads
moved.
