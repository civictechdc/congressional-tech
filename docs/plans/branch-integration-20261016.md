# Integrate local main with the pushed branches

Status: proposed, 16 October 2026; revised at 18:30 EDT. Phase 1 can start now. Phase 0 (finishing checkpoint 19) gates Phases 2–4, and it needs an explicit resume.

## Blocker: checkpoint 19 was killed, nothing published

The checkpoint-19 publication (runner `output/corpus-retry-20261015/runner-checkpoint19-publication`, attempt 1) stopped at 18:20:06 EDT during its first phase (`recover_capture_associations` in the catalog build). The ChatGPT/Codex desktop app exited at that moment. The runner (PID 75976) was a child of that app's `codex app-server` (94792), not a launchd job, so the whole process tree went down with it. The Codex monitoring thread's last event carries the same timestamp. No crash report exists, and the cause of the app exit is unknown.

State after the kill, all checked directly:

- `publication-checkpoint19/continuation.json`: `phases: {}`, `writes: {}`. No phase was accepted and no remote write is recorded. R2 and the public viewer still serve checkpoint 16's publication.
- `run_corpus_recovery.py status` reports `requires_reconciliation` (supervisor and child dead, no `exit.json`). By design the runner will not relaunch on its own.
- All 260 pinned inputs in `publication-checkpoint19/pins.json` re-hash unchanged: 228 runtime, 16 integration and 16 primary files. The binding is intact.
- Both locks (`.cache/local-recovery.lock`, `.runner.lock`) are free. `build/working.sqlite` is a 15 GB partial build; the design does not resume an incomplete SQLite computation. Free disk is 54 GB (97% used).

## Phase 0 — finish checkpoint 19 (owner approval required; it publishes)

Resume checkpoint 19 on its pinned runtime before integrating. Do not republish it from the integrated branch: that would combine new recovery data with the house-naming 3.0.0 → 3.2.7 classification change in one publication, and it would need fresh pins and readiness.

1. `run_corpus_recovery.py reconcile` on the runner directory to record the lost attempt honestly (it sets `remote_state_verified: false`).
2. Run the saved `explicit_publication_resume` command from `docs/recovery/next-batch-command-handoff.json` under the runner's resume path. With no accepted phases, it rebuilds the catalog from the start: expect about an hour or more and a peak near 9.4 GB. Decide whether to delete the 15 GB partial `working.sqlite` first, or let the resume overwrite it.
3. **Launch it detached from any app session** (a launchd job, like the earlier `org.codex.*` runs), so that quitting the desktop app or ending a chat session cannot kill it again. This is the root cause of the loss.
4. Gate: actual exit 0, then exact catalog, mapping and viewer readbacks plus live public coverage, recorded in `current-continuation.json`.

## Where things stand

| Head | Commit | Relation | Role |
| --- | --- | --- | --- |
| `main` (local) | `83f8823`+ | 163 ahead / 42 behind `origin/main`; merge-base `f61eb09` | Recovery MVP, docs/recovery, cleanup commits. Not pushed. |
| `origin/main` | `1a57561` | — | The public filename website (Oct 13–15) |
| `origin/codex/document-kind-publish` | `a516006` | `origin/main` + 63, pushed and deployed | house-naming 3.1.0→3.2.7 rules, 91 content reviews, reviewed-category publishing, newest local viewer |
| `codex/viewer-direct-detail` | `c361df3` | `origin/main` line + 2 | Rollback runtime. Its fix is in `main`; its test is not |
| runtime worktree | `fcc65a6` | `c361df3` + reviewed overlay | Pinned `--runtime` of checkpoint 19 (`refs/archive/recovery-mvp/runtime`) |
| integration worktree | `a8e9411` | ancestor of `main` | Pinned dispatcher scripts of checkpoint 19 |
| `wip/document-recovery-gaps` | `5064990` | `ff21142` + 1 | Binary-preamble PDFs and `rel=alternate` links; changes the evidence fingerprint |
| `wip/webharvest-discovery` | `d746ae5` | `ff21142` + 1 | Web Harvest target discovery; needs `surt` declared first |

### What `main` lacks: the website itself

Three Codex threads built the viewer in separate worktrees, and all of it is pushed. The Oct 13 threads in `static-filename-viewer`/`accepted-recovery-status` built the static website. The Oct 14–15 Web Harvest thread fixed saved-link counts (`c887b83`, `82281d8`, `d1fa9bd`). Both of those landed on `origin/main`. The Oct 15–16 document-kind thread worked on `document-kind-publish`, including local viewer previews and review publishing, which is deployed. `main` forked on 10 October for recovery work, before the site existed. The recovery threads copied in only what publishing needed.

Of the 111 files `origin/main` changed since the merge-base:

- **44 identical in `main`**, copied in by the `27f9ddd` seed.
- **38 missing from `main`**: `apps/site/src/pages/filenames.astro` and the `filename-*.mjs` components, the `apps/viewer-data` Worker that serves the R2 data, `publish-filename-viewer.yml` and its tests, `catalog_availability.py`, `catalog_lineage.py`, about 7 tests and about 10 design and performance notes. From `main` alone you can publish catalog data to R2, but you cannot build or deploy the page that reads it.
- **21 still at the merge-base version in `main`**, which `origin` advanced (`raw_catalog.py`, `catalog_staging.py`, `deploy-pages.yml`, `apps/site/package.json`, `Header.astro`, among others).
- **8 edited on both sides**, covered by the conflict table below.

The merge brings in all 38 and advances the 21 without conflicts. The newest local viewer (`filename-viewer.html`/`.mjs`, `view_document_filenames.py`) is the `document-kind-publish` version; `main`'s copy is from 13 October.

### Conflicts

Merging `document-kind-publish` into `main` yields 13 conflicted paths; everything else merges cleanly. This was re-checked against `83f8823` and `a516006` at 18:30 EDT. Each conflict is one side's copy of the other side's commit, not an independent edit:

| Paths | Take | Why |
| --- | --- | --- |
| `apps/site/scripts/publish-filename-viewer.py`, `publish-viewer-r2.py` | **ours** (`main`) | `main` = `c887b83` (the version `document-kind-publish` carries, unchanged since) + `c361df3` + reviewed overlay (`53e7ef0`, `4e77661`, `89b6213`). Byte-identical to the pinned runtime. |
| `filename-viewer.{html,mjs}`, `tests/test_filename_viewer_ui.mjs`, `tests/test_document_filename_viewer.py`, `parsers/document_cover.py` | **theirs** | `main`'s only change is `feb004c`, the same patch as origin `588ec1f`. |
| `scripts/view_document_filenames.py` | **theirs** | Besides `feb004c`, `main` has `03a5231`, a backport; every line it added is already in `a516006`. |
| `retention/document_index.py`, house-naming `__init__.py`, `guide.json`, `guide.schema.json`, `tests/test_reviewed_house_publishers.py` | **theirs** | `main`'s only change is `ec0e400`, a cherry-pick of origin `1a57561`; 8 rule commits build on it. |

## Decision: merge, then rebase only the small unpublished branches

Merge `document-kind-publish` into `main`. Do not rebase `main`. Rebasing would replay the same conflicts across about 7 commits and rewrite SHAs that evidence pins: checkpoint 19's binding names `a8e9411` and `fcc65a6`, and `ee728cf` and `c361df3` are cited in `docs/recovery/`. The three duplicate pairs (`feb004c`≡`588ec1f`, `ec0e400`≈`1a57561`, the `27f9ddd` seed of `c887b83`/`c361df3`) are absorbed by the merge, so leave them.

Rebase only the two `wip/*` branches, each one commit, onto the merged result when they land.

## Phase 1 — build the integration branch (safe now, in parallel with Phase 0)

Do this in a new worktree. Never switch or rewrite the primary checkout or the two pinned worktrees: their bytes are part of checkpoint 19's binding, and the primary `.venv` holds editable installs of the primary checkout's packages.

```sh
git fetch origin
git worktree add -b integrate/main-dkp ~/.codex/worktrees/integrate-main-dkp/congressional-tech main
cd ~/.codex/worktrees/integrate-main-dkp/congressional-tech
git merge --no-ff origin/codex/document-kind-publish
git checkout --ours -- apps/site/scripts/publish-filename-viewer.py apps/site/scripts/publish-viewer-r2.py
git checkout --theirs -- docs/youtube-coverage/research/filename-viewer.html docs/youtube-coverage/research/filename-viewer.mjs \
  docs/youtube-coverage/research/scripts/view_document_filenames.py tests/test_filename_viewer_ui.mjs tests/test_document_filename_viewer.py \
  packages/congress_api/src/congress_api/parsers/document_cover.py packages/congress_api/src/congress_api/retention/document_index.py \
  packages/house-naming/src/house_naming/__init__.py packages/house-naming/src/house_naming/data/guide.json \
  packages/house-naming/src/house_naming/data/guide.schema.json packages/house-naming/tests/test_reviewed_house_publishers.py
git checkout c361df3 -- tests/test_filename_recoveries.py   # a3c4528's test for the fix main already carries
git grep -n '^<<<<<<<' && echo 'unresolved markers'
git add -A && git commit
```

Verify with a separate environment, because the primary `.venv` resolves packages from the primary checkout. Use the project's own commands (from `update-data.yml` / `capture-raw-sources.yml`), not tools on `PATH`:

```sh
uv venv .venv-integ
uv pip install --python .venv-integ -e 'packages/house-naming[test]' -e packages/committee_meeting -e packages/congress_shared \
  -e packages/youtube_api -e 'packages/congress_api[archive,test]' -e apps/committee_youtube 'PyYAML>=6,<7'
.venv-integ/bin/python -c "import congress_api, house_naming; print(congress_api.__file__, house_naming.__version__)"  # worktree path, 3.2.7
.venv-integ/bin/python .github/scripts/offline-python.py -m pytest -q tests packages/committee_meeting/tests packages/house-naming/tests .github/tests
(cd apps/site && npm install && npm run test:explorer && npm run check:explorer-types && npm run build)
```

The `npm run build` step is the first proof that the merged tree contains a buildable website. While checkpoint 19 runs, run the test suites under `nice` or afterwards: the publication peaks near 9.4 GB, and disk is at 97%.

## Phase 2 — after checkpoint 19 exits and its readbacks pass

1. Remove the `recovery-mvp-integration`, `recovery-mvp-runtime` and `viewer-retained-sync` worktrees. Delete `codex/viewer-direct-detail`; its fix and test are now in `integrate/main-dkp`. `refs/archive/recovery-mvp/runtime` keeps `fcc65a6` reachable for the citations.
2. In the primary checkout, restore the deferred files: `git checkout HEAD -- packages/congress_api/src/congress_api/acquisition/house_sites.py` (a partial revert of `009dca6`; the patch is saved in `.cache/repo-cleanup-20261016/`) and the four parser/evidence files, plus `rm tests/test_document_recovery_gaps.py` (all in `wip/document-recovery-gaps`). Delete `publication-checkpoint19/build/working.sqlite` once the readbacks pass.
3. `git merge --ff-only integrate/main-dkp` on `main`, then `git push origin main`. This is a fast-forward for origin, because `origin/main` is an ancestor. Pushing is the owner's call.

## Phase 3 — deliberate re-baselines, one at a time

- **house-naming 3.0.0 → 3.2.7** changes `document_kind` values; recovery evidence pins 3.0.0. Take the next recovery publication after checkpoint 19 from the integrated runtime as a declared re-baseline.
- **Reviewed-category search** (`document-review-publication.json`) is pinned to catalog `d42b9f66…`. `loadReviews` returns nothing when the catalog ID differs, so rebind the review bundle to the checkpoint-19 catalog as soon as it publishes, or reviewed search goes dark on the public site.
- **`wip/document-recovery-gaps`**: `git rebase main` and land it as its own re-baseline. `evidence_fingerprint` now hashes `document_links.py`, so all document evidence is re-read and link counts change. Expect conflicts in `archive_links.py` and `capture_metadata.py`, which `document-kind-publish` also changed.
- **`wip/webharvest-discovery`**: declare `surt` as a dependency first, then rebase and land it.

## Phase 4 — remote and side cleanup (owner's call)

- Delete merged remote branches: `origin/codex/initial-population-ci` and `origin/codex/house-alert-diagnostics` (both ancestors of `main`), and `origin/codex/document-kind-publish` after Phase 2.
- Leave `origin/78-implement-library-for-data-warehouse`: it is another contributor's branch, and its PR #79 was closed unmerged.
- `~/Work/pipeline-data` is a CI-overwritten orphan snapshot from 26 September. Refreshing it means a 1.4 GB fetch of `origin/pipeline-data`; do so only when it is needed.
- `packages/committee_meeting/CONGRESS_API_INTEGRATION.md` (lines 45, 72) links into the removed `congressional-tech-production` worktree. Repoint those links to repository-relative paths.

## Rollback references

The cleanup on 16 October preserved everything it removed:

- `archive/document-catalog-20261016`: the document-catalog package and its uncommitted work.
- `refs/archive/recovery-mvp/{acquisition,import,publication,runtime}`: the detached work packages and the runtime that the recovery docs cite.
- `refs/archive/branches/{claude/hearing-text,codex/primary-recovery-20260928}`: the two squash-merged branches whose equivalence was indirect.
- `.cache/repo-cleanup-20261016/*.log`: every removed worktree, deleted branch SHA and unloaded launchd job.
