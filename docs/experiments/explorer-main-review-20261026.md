# Explorer repair merge and review — October 26, 2026

## Merge

The 24 scoped repair commits were merged and pushed to `main` at
`ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`, from remote base
`c466a45e09e27bde48ade12454f8b458c3643d21`. The primary checkout was
fast-forwarded. Its existing tracked edits were preserved byte-for-byte; the
unrelated MCP files and proposed-design document remain outside this repair.

The original lookup diagnostic is committed with a historical-status note.
Superseded capacity implementation `5c581a6e` and test workaround `6607c552`
were intentionally excluded; their useful final replacements are integrated.

## Verification

- **723 publication/workflow tests and 2 subtests passed** in 109.52 seconds.
  Runtime/test source is `2a1aafe6`; `ad222085` adds only evidence documentation.
  The suite includes the complete `viewer_publication` test package, publication
  scripts, preflight, native runtime setup, workflow checks, upload behavior, and
  Pages dependency checks. Real native fixtures used the qualified local binary
  and isolated fixture workspaces.
- **235 data/collector tests passed** in 80.94 seconds at `157795a0`. None of
  those implementation or test files changed before the merge.
- **154 maintained JavaScript explorer tests passed** in 9.60 seconds at
  `d36564b1`. Their implementation and fixture source did not change afterward.
- A separate 202-test capacity/local-journal/status/identity run passed after
  `d36564b1`; it overlaps the final 723 tests and is not an additional count.

The five failures in the first broad upload test run were stale full-readback
expectations and an incomplete HEAD mock. Commit `2a1aafe6` replaces them with
checks for zero payload reads after acknowledged uploads, one reconciliation
read for uncertain outcomes, no repeated PUT, failed-PUT refusal, and bounded
public smoke-check failures. The focused file passed 32 tests; the final broad
run above is green.

Logs: `/tmp/ct-merge-publication-final-20261026.log`,
`/tmp/ct-merge-data-tests-20261026.log`, and
`/tmp/ct-merge-js-tests-20261026.log`. These are local execution receipts, not
proof of a completed production release or its duration.

## Findings and follow-up fixes

The final source is `0cde0d348dce0c5eae714a7199b54839dab8bc23`, which adds the
bounded smoke-read fix to `6183938fcb2b0842d5e1f59072383aa7dd251d32`. Subsequent
commits add only review records. Six focused commits address seven findings:

| Finding | Integrated fix | Evidence |
| --- | --- | --- |
| Checkpoint verification consumed time without reducing the child's preparation allowance. | `a82cfb55` uses the absolute job deadline and refuses a launch after it expires. | Independent reproductions cover slow verification and exhausted budget. |
| Release identity omitted the maintained publisher modules, constants, and native Python client. | `c4326f58` hashes those maintained sources. | Mutation checks prove each newly included file changes the identity. |
| Production capture replay could substitute different cached values when schemas and row counts matched. | `c7b678bf` reads the selected capture batches through the maintained snapshot reader. | Same-shaped changed values no longer replace the selected input. |
| Interrupted raw qualification trusted its interpreted Parquet file without checking its saved identity. | `c7b678bf` records and verifies the interpreted-file checksum. | Valid resume succeeds; modified bytes are refused before publication. |
| Weekly GPO observations omitted failed MODS/manifest check timestamps. | `a3beabac` includes those retained checks in observation timing. | Rejected-only and stale-parser failure cases remain recorded and retryable. |
| Public Parquet smoke checks could read an oversized response without a byte bound. | `0cde0d34` reads four expected bytes plus one overflow byte. | Both native and earlier-format probes reject oversized bodies; 44 upload/native/identity checks pass. |
| The single-pass occurrence writer limited rows but not retained decoded bytes. | `6183938f` flushes before its byte budget and refuses an oversized row. | Four regression cases check limits and row/order preservation. |

The occurrence fix can change Parquet row-group boundaries and file bytes while
preserving logical rows and order. Publication source identity changes with
these fixes; an artifact from another code identity is not accepted as current.

Follow-up verification passed **264 cross-cutting Python checks**, **126
renderer/native checks**, and **154 JavaScript checks**. These overlap the
initial runs and are not additive release-wide test counts. The first run used
`a3beabac`; the later occurrence changes were covered by the renderer/native and
JavaScript runs at `6183938f`. Logs are
`/tmp/ct-post-review-integration-20261026.log`,
`/tmp/ct-post-review-occurrence-20261026.log`, and
`/tmp/ct-post-review-js-20261026.log`.

## Parallel rebase and review

All eight task owners preserved backup refs, rebased their owned worktrees, and
reviewed the combined source. The capacity task also collected three subagent
reviews. All eleven scoped verdicts are **APPROVE** after the fixes. Review
reports identify exact source revisions, functions, callers, data flow,
regressions, executed checks, and evidence limits. The bounded smoke fix received
capacity review and the integration owner's final 44-test check.

| Owner | Report | Final scope result |
| --- | --- | --- |
| Index and local/status capacity | [index](reviews-20261026/index.md) | Approve; no additional code defect. |
| Renderer resume | [resume](reviews-20261026/resume.md) | Approve; independently reproduced and verified the deadline fix. |
| Workflow and Pages gate | [workflow](reviews-20261026/workflow.md) | Approve; deadline repaired and v5 refusal verified. |
| Raw source recovery | [raw](reviews-20261026/raw.md) | Approve; both recovery checks fixed; GPO timestamp fix independently checked. |
| Test imports and source identity | [tests](reviews-20261026/tests.md) | Approve; source fingerprint completed. |
| GPO acquisition and retention | [gpo](reviews-20261026/gpo.md) | Approve; failed observations retained; raw fixes independently checked. |
| YouTube | [youtube](reviews-20261026/youtube.md) | Approve; all 119 pins and stable storage keys checked. |
| Capacity and uploads | [capacity](reviews-20261026/capacity.md) | Approve; occurrence and smoke-read resource bounds fixed. |
| Inventory subagent | [inventory](reviews-20261026/capacity-inventory.md) | Approve; one local-only duplicate directory walk remains an optional optimization. |
| Journal subagent | [journal](reviews-20261026/capacity-journal.md) | Approve; no blocking correctness finding. |
| Occurrence subagent | [occurrences](reviews-20261026/capacity-occurrences.md) | Approve; byte-bound fix integrated and logical output verified. |

Two nonblocking notes remain: the local saved-phase recovery path walks its
directory twice (the hosted path walks once), and the leftover-process-group
refusal branch lacks a dedicated regression test. Neither is a demonstrated
correctness defect or a prerequisite to the scoped merge. Production release
speed and memory remain unmeasured at full-catalog scale.

## Hosted state

The original source push started raw-source validation, Committee Explorer
publication, and Pages. [Pages run 40388067405](https://github.com/civictechdc/congressional-tech/actions/runs/40388067405)
reached the real-worker gate and failed with `Unsupported filename catalog version.`
Deployment was skipped. This is the expected refusal while selected data is v5.
A fresh bounded read at 2026-10-26 19:39 UTC confirmed version 5 at release
`03fc4cfd93a74fdc9be16d41dc528207`.

The filename publication workflow is `disabled_manually`; neither merge started
a v6 publication. Source merge, hosted checks, collector execution,
site deployment, and selecting a v6 data publication are separate results.

Hosted checks at the last inspected revisions:

- [Raw validation at `ad222085`](https://github.com/civictechdc/congressional-tech/actions/runs/40388067402): passed.
- [Raw validation at `6183938f`](https://github.com/civictechdc/congressional-tech/actions/runs/40389327174): in progress at the status snapshot.
- [Pages at `6183938f`](https://github.com/civictechdc/congressional-tech/actions/runs/40389327125): failed at the same data-version prerequisite; deployment was skipped.
- [Committee publication at `ad222085`](https://github.com/civictechdc/congressional-tech/actions/runs/40388067565): in progress; [the later run](https://github.com/civictechdc/congressional-tech/actions/runs/40389327402) is queued.

No manually disabled workflow was enabled or dispatched. No v6 completion or
new deployment is claimed by this merge/review record.
