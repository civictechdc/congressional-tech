---
id: ct-arlk
status: closed
deps: []
links: [ct-b7bv, ct-ucwm]
created: 2026-11-11T00:44:38Z
type: chore
priority: 3
assignee: mikewolfd
tags: [disk, model, harness]
---
# Model-only build folders keep about 1.6 GiB each and nothing removes them

Found 2026-11-10 by W3's review (docspec-feedback refactor). archive_model_job --from-candidate leaves one build folder per arm: model-spec.json, runtime.json, workspace/, ledger/ (when derived), archive-release/ and archive-model/. Measured by du at 00:44Z on 2026-11-11 (clock read): refactor/captures-step/build2-control and refactor/postmerge/build3-control are 1,635,228 KiB each; archive-model 1,473,984 KiB, of which archive-model/evidence (the 18 evidence Parquet files) 1,464,324 KiB; archive-release 160,568 KiB; workspace empty after the build. Nothing removes a build folder (the command's --build help says so), and the earlier hand-built folders (release-next/build-*) are still on disk. A harness of N arms leaves about N x 1.6 GiB; free disk was 54.0 GiB (df) at 00:44Z. The evidence files are what the identity comparison reads (count 2, sha256 of each, refactor/captures-step/cs_compare.py), so they cannot go before it has run.

## Acceptance Criteria

Model-only build folders have an owner and an end condition through the existing cleanup facility, not a new retention authority: for example, once the identity comparison has recorded the release id and the sha256 of every archive-release and evidence file, output and scratch are removed and the spec, runtime copy, result line, watchdog report and comparison are kept; or a recorded decision keeps them under a measured disk budget (ct-ucwm). Free disk measured before and after.


## Notes

**2026-11-11T14:31:18Z**

validated 2026-11-11, left open: nothing removes model-only build folders yet; archive_model_job --from-candidate still leaves output and scratch, and release-next/ still holds build-final-2, build-final-3, build-main-control and build-release-b. Needs an owner and end condition (cleanup facility or a measured budget under ct-ucwm).

**2026-11-12T05:19:00Z**

resolved on `claude/ct-wave-1ab-safety`:
1. Added `retire_model_build(build, *, execute=False)` to the existing disk-cleanup facility (`scripts/archive_disk.py`) and wired `--retire-build <folder> [--plan | --execute]` into `viewer_publication.archive_model_job`.
2. Before deleting `archive-model`, `archive-release`, `workspace`, and `ledger`, `retire_model_build` verifies `build` is a private model-only build (refusing symlinks and any folder containing `archive-publish` or `archive-daily`), copies `steps.jsonl` to `build/steps.jsonl` if absent, and atomically writes `retired-build-digests.json` recording `release_id` and the `sha256` + byte count of every `archive-release` and `archive-model/evidence` file plus `job.json`/`result.json`. Covered by unit tests in `scripts/tests/test_archive_disk.py` and `packages/viewer_publication/tests/test_archive_model_job.py`.
3. Retired the four superseded 2026-11-10 `release-next` builds (`build-final-2`, `build-final-3`, `build-main-control`, `build-release-b`, `6,790,668,071` logical bytes across `archive-model`/`archive-release`/`ledger`/`workspace`, zero open `lsof` handles). Measured `/System/Volumes/Data` free disk before and after (`df -k` / `df -h`): `67,690,324 KiB` (`65Gi`) -> `73,538,928 KiB` (`70Gi`).
