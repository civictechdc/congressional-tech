---
id: ct-ud0b
status: closed
deps: [ct-itcg, ct-whm2]
links: [ct-4jms, ct-tk10, ct-082q, ct-9lxf, ct-gc99, ct-9j3z]
created: 2026-11-02T13:59:14Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, gates, daily, phase2]
---

# Publish eligible nightly additions and resume completed work

Keep the archive fresh from new receipts and preserve the selected release when a candidate requires review. The restored Mac job is scheduled for 05:30 local. At the November 5 audit, launchd showed zero invocations since restoration after `e145d24c389e`. The earlier nightly attempt completed daily inputs and refused a mixed candidate at Gate 1. The approved e145 publication reused a checkpoint through the maintained publisher under a separately approved run.

The automatic new-document path has a gap. A genuinely new attempted request URL produces an added `url_state.parquet` row, which the current Gate 1 allowlist refuses even if the new document otherwise qualifies. The scheduled wrapper also cleans ignored outputs that hold completed model artifacts. The controller already has exact-input checkpoint reuse, but the normal scheduled path does not carry those artifacts into a retry. [e145 release](../docs/releases/2026-11-05-e145d24c389e.md)

## Acceptance Criteria

- Extend the existing Gate 1 positive fixture with a native-shaped new-document case and its newly attempted request URL. Admit the dependent URL-state row only when it traces to the same qualifying raw receipt lines as the added document, with receipt keys outside the selected release and dates later than its inputs. Preserve refusal fixtures for changed or removed values, old or untraceable receipts, unsupported queued entries, and unrelated added entity rows. Retain the existing link and producer checks.
- Make the normal Mac wrapper preserve a completed candidate and the artifacts its checkpoint pins before scratch cleanup. Reuse the existing exact-input checkpoint and pointer reconciliation on a matching retry. Keep a reviewed refusal and its evidence available. Use fresh work when inputs differ and record the reason a checkpoint cannot be reused. Verify an interruption after model completion through the normal wrapper, including preserved pointer and no repeated model build for the matching retry.
- Preserve current receipt discovery, oldest-first readings budget, body custody, and pinned producer records. Record incomplete daily work as failure. Use the existing run and release records.
- Observe the existing Mac schedule. Record the selected commit, daily result, gate outcomes and pre/post release pointer. A refusal must retain the reason and preserve the pointer. Before claiming automatic publication works, show a genuine qualifying additions-only candidate pass all five checks before the pointer flips. An unchanged run or safe refusal records an operational outcome.

[November 5 root-cause analysis and source evidence](../docs/plans/production-mvp-root-causes-round2-20261105.md).

## Notes

**2026-11-02T15:55:47Z**

2026-11-02 impl-h r1b-h 1573be5c: implemented (3f122fc8): automatic_causes accepts a difference only when every new row is a new document whose body comes from a receipt outside the live release's set, dated after its newest, named by its raw receipt line; any changed or removed value, split, old or undated receipt, or untraceable row refuses. Four acceptance tests plus one through publish_candidate. Can't see: a bug that only adds wrong rows from new receipts. Still blocked on the daily path by gate 5 until daily production writes per-snapshot producer records (follow-up).

**2026-11-02T18:17:49Z**

2026-11-02 spec-run: the selective job's D2 stopped after 8 s with all 67,565 reads pending and no location (peak 1.65 GiB). archive_selective._daily writes an empty body inventory, points local_root at a directory that doesn't exist, and passes the raw store only for unreadable decisions. Any non-empty D2 work therefore never reads bodies, which would hit nightly production runs as well as local ones. impl-e2 is fixing it first, as one body-source binding (local mirror or R2) through readings' existing remote/body_store path, with fail-first tests that read non-empty work; then the r4-u2 rebase.

**2026-11-02T18:44:42Z**

2026-11-02 causes dry run: the model's measured 14-17.5 GiB peak (before fix 1 and the engine spill fix) doesn't fit the ubuntu-24.04 hosted runner (16 GB RAM), and the model materializes about 38 GB with spills up to 53.4 GB (profile_completeness capture_dup, being fixed upstream by engine-spill) against runner disk. A daily publish spec can't pass gate 5 until ct-ud0b's daily producer records exist. This release runs on the Mac (owner decision), so it isn't blocked; nightly hosted publishing is. Owner decision on runner capacity (larger hosted runner vs self-hosted vs further cuts) once fix 1 and the spill fix are measured.

**2026-11-02T20:21:07Z**

2026-11-02 measurement for the runner decision: the full model at release settings on engine b0342a7 peaked at 9.40 GiB RSS (16 GiB pool, 2 threads), under the 16 GB ubuntu-24.04 runner; the capture_dup spill drops to about 0.4 GB with the backport. Disk and runtime on a runner are still unmeasured.

**2026-11-02T20:55:01Z**

2026-11-02 train/spec-run: setup-native-runtime.py hard-codes a 120 s engine-call timeout, which would kill a hosted full model run (the local release run needed more). It must come from the job's declared limits before any hosted model or nightly run.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.

**2026-11-04T02:21:36Z**

Reopened 2026-11-03 (post-release acceptance test): automatic causes work, but the hosted nightly path cannot publish yet. Blocked by ct-r8jd (rss_gb) and ct-itcg (the daily job's canonical archive.* tables still hold v21, not the live release's inputs, so Gate 1 would refuse every nightly candidate).

**2026-11-04T02:29:12Z**

2026-11-03: ct-itcg closed (specs pinned to archive_r1b); publish binding admits with rss_gb 14. Dropped the ct-r8jd dependency: what remains there is maintenance only. Remaining here: one hosted nightly run that builds from the archive_r1b base, passes Gates 1-5 and publishes (or refuses with a recorded reason).

**2026-11-04T02:33:37Z**

2026-11-03: pushed specs (origin/main 655476f2); publish --check-binding --github-output passes locally. Not dispatched; a hosted run would fail: (1) GitHub has no archive-publish/archive-backfill/archive-maintenance environments and none of ARCHIVE_PUBLISH_ENGINE_CREDENTIALS, ARCHIVE_PUBLISH_R2_ACCESS_KEY_ID, ARCHIVE_PUBLISH_R2_SECRET_ACCESS_KEY (repo has only R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, DOCSPEC_ENGINE_CREDENTIALS); (2) spicy-regs inputs exist only under local .cache (ct-whm2). DOCSPEC_RUNTIME_ARTIFACT matches model/docspec-runtime-pin.json (b0342a73, linux-amd64 9e5cc34f). archive-jobs.yml has never run. The workflow_run trigger also needs capture-archive enabled (ct-4jms).

**2026-11-04T03:16:11Z**

2026-11-03: re-enabled archive-jobs.yml (owner decision; it had been disabled by hand 2026-10-28) and dispatched publish run 41763463814. Binding, spicy-regs fetch, runtime install with repo-wide secrets, site build and Gate 3 passed; the publisher refused 'job requires explicit host limits' (remote installs never wrote limits; watchdog peak 0.91 GiB). Fixed: .github/docspec-hosted-limits.json (10 GiB pool, 10 GiB spill, 4 threads) written by setup-native-runtime for remote installs.

**2026-11-04T03:22:00Z**

2026-11-03: run 41766051564 (with hosted limits) reached the daily producer's readings plan job, which was killed at the hard-coded 120 s engine timeout (watchdog peak 2.15 GiB). Remote installs now default to 3600 s, the release's setting.

**2026-11-04T03:32:47Z**

2026-11-03: run 41766667237 completed the daily producer on the runner (~5 min, watchdog peak 2.20 GiB), then completed_daily_inputs refused: video_records parser_versions missing, because the merge rebuilt parser_versions from the daily run only. Fixed to carry the template's Explorer parser versions; regression test replays the checked-in template.

**2026-11-04T03:56:39Z**

2026-11-03: run 41767790801. Attempt 1 failed on one transient R2 read timeout (single-attempt client, receipts/congress/meetings/2026-09-28/assemble-20260930.jsonl.gz); attempt 2 completed the daily producer and the Explorer merge, then Gate 5 refused all 7 tables: 'no producer record (job and commit) for the pinned snapshot' (watchdog peak 2.20 GiB). publish.json has no 'producers' field and the daily producer writes none. Remaining, in order: (1) check in the release's 7 import records (work-live/producers/*.json) and pin them in publish.json for tables daily leaves unchanged; (2) have the daily producer write a per-snapshot record for each table it appends, naming its job and commit with the prior record as base, and teach snapshot_reasons to accept that chain; (3) runner capacity: the 11-02 dry run measured ~38 GB materialized and spills up to 53.4 GB, beyond the standard runner's disk and the 10 GiB hosted spill limit; the owner decision recorded on 11-02 (larger hosted runner, self-hosted, or further cuts) is still open. The workflow is enabled; capture stays disabled, so only manual dispatch and the Sunday maintenance schedule (which refuses at binding, ct-3szv) run.

**2026-11-04T12:46:09Z**

Owner decision 2026-11-04: the nightly runs on the owner's Mac on a schedule (launchd), not a GitHub-hosted runner; a parallel investigation compares the current model build's memory and spill with the v21 run. Daily now discovers new receipts in R2 (22 families) and appends only the oldest receipts whose new bodies fit max_work_items (83c673aa); measured backlog on 2026-11-04: 29,414 receipts, 22,714 of 22,775 new bodies from 2026-10-31, all dated after the live cutoff 2026-10-28.

**2026-11-05T21:33:58Z**

Fresh independent acceptance on `dd9a6f82` found that a link added to an existing document could inherit automatic approval. `9c3ee247` fixed the attribution check and merged into local `main` at `5aa78701`. The correction passed 109 focused Gate 1, comparison and publisher checks plus the independent planted case. Integrated fixtures reused a 7.3 MB model result, reconciled a lost acknowledgement with one pointer write, and preserved the selected release on refusal. Both merged worktrees and branches were pruned after their exact tips were archived. [Acceptance and cleanup](../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/acceptance/nightly-freshness/HANDOFF.md)

Keep open for a genuine scheduled additions-only run that passes all five gates and records the selected commit, daily result, gate outcomes and pre/post pointer. The all-wave hold still covers the Mac schedule. `ct-9lxf` owns complete-operation disk measurements for a fresh nightly run, a compatible retry and backfill.

**2026-11-05T23:55:28Z**

The nightly approval and completed-candidate recovery changes are merged at 04f41b28 and 5aa78701. Independent checks passed 109 focused controls, reused the retained 7.3 MB result, reconciled a lost acknowledgement with one pointer write and preserved the selected release on refusal. [Independent acceptance](../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/acceptance/nightly-freshness/HANDOFF.md)

Close implementation. cef-96wc now owns scheduler restoration and a genuine Mac additions-only run through all five gates, with commit, daily result and pre/post pointer readback. A crash before the producer record is written still requires reconciliation. ct-9lxf retains whole-operation disk/spill checks; ct-4jms retains hosted scheduled capture. The Mac schedule remains disabled until release readiness.
