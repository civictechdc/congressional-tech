# Congressional-tech DDK replacement

The replacement is in progress in this isolated worktree. Corrected preparation
is independently approved and committed as `706de09e`. The first definition
bridge remains an uncommitted migration experiment. It needs redesign to reduce
custom conversion and duplicated checking; a released DDK loader defect also
blocks its compiler. **No end-to-end replacement
acceptance, external publication or production cutover is complete.**

The parent verified the dev2 local release and changed `implementationReady` to
true. External DDK publication is separate. The shared DDK/runtime successor is
parent-owned and must be qualified before this application uses new capabilities.

| Artifact | Purpose |
| --- | --- |
| [Status](status.json) | Current completed, uncommitted, active and blocked work |
| [Work allocation](work-allocation.json) | Agent ownership and independent review roles |
| [Design](design.md) / [operation seams](operation-seams.md) | Full delivery scope, owners, native requests, qualification and per-product activation |
| [Acquisition lifecycle](acquisition-lifecycle.md) / [capabilities](acquisition-capabilities.json) | Source/retention and recovery behavior, exact citations and planned proofs |
| [Model and consumers](model-consumers.md) / [capabilities](consumer-capabilities.json) | Native schema/ID, field, relationship, recipe and journey inventory |
| [Acceptance plan](acceptance-plan.md) | Independent connected and lifecycle proofs; all unexecuted obligations remain visible |
| [Runtime gaps](runtime-gaps.md) | Concrete shared dependency requests, restrictions and missing evidence |
| [Architecture review](reviews/architecture-review.md) / [acceptance review](reviews/acceptance-review.md) | Independent findings; reviews are evidence, not implementation passes |
| [Definition code review](reviews/definition-code-review.md) | Provisional bridge findings and repair dispositions; not adoption approval |

The user's acceptance criterion is a cleaner, streamlined catalog-to-validation
stack. The next increment must migrate a real consumer to the standard catalog
and retire its superseded current path. Exact legacy JSON formatting and a
second schema validator are not end-state requirements. The concrete criteria
are in [the design](design.md#simplification-is-part-of-acceptance).

The provisional default publication hook and added model hash inputs have been
withdrawn. Both incumbent source files and the production package dependencies
match the baseline. The unchanged DDK wheel is a workspace development dependency;
its lock and this worktree's environment were synchronized successfully.

Baseline: `a06eb64bf3caa4a44e12a89bdd08939323de3092`, branch
`codex/ddk-congress-replacement-20261106`, worktree
`/Users/mikewolfd/.codex/worktrees/9c45/congressional-tech`.
Current main has separate ongoing work and is not modified by this task.

DDK tested implementation is `8e9a53e81ec6258f2068557ff5e4788c80c32995`,
documentation `3d2622b7a1cd0a454451987cd0ff7faf29d86e21`, wheel SHA-256
`b705e81c15636522c4e0e41f202ee3717d264800cdf0984c91f76ab925b4cd0e`.
DocSpec is `b1270b2e964becc5844bb6ca95ee5d605c7a3d79`, full native binary
SHA-256 `b89b43e2d2bf17f8d87ff1d9a779e06c3a024f2777e2327a8f048c6cb00a2532`.
The originally supplied dev1 commits exist and remain historical evidence;
they were not substituted for current release readiness.

Durable preparation snapshots were partially copied to main's
`.cache/archive-release/ddk-replacement-20261106/preparation-01/` by an approved
command. It stopped before its success record because it assumed a nonexistent
`qualified-03/runtime-verification.json`. That incomplete attempt remains intact.
The actual record is
`/Users/mikewolfd/Work/artifacts/ddk-stack-20261105/runtime/verification.json`,
SHA-256 `520c8a157564c6be95df2415f4863e92702111a6fa9d6a6bce75fb9f1585fea7`;
the retained `qualified-02/runtime-verification.json` copy is equivalent. Dev2's
installed test capture is in `qualified-03/run.json` and `junit.xml`. No new
native verification or corpus replay is implied by these references.

`uv sync --frozen` and the required local ticket index refresh completed. The
focused test preflight passed with the retained Poppler 26.06.0 installation and
the unchanged congressional native runtime pin. The first test then failed in
released DDK `core._catalog_dependencies`: it indexes `target.dataset` for a
schema-valid external target and raises `KeyError: 'dataset'`. The shared DDK
owner must fix and qualify this behavior; this worktree preserves the external
relationships and the frozen package.

The durable log and JUnit result for the provisional integration are under main's
`.cache/archive-release/ddk-replacement-20261106/checks-01/`. This was a partial
run of one of 495 lane files, exit 1. No full Python lane, browser suite, native
job or replacement acceptance has completed. The failed run does not establish
acceptance of the subsequently revised experiment. All 191 source-definition hashes
and sizes in `native-profile.json` independently match the stated Git baseline.

The latest local disk check found 8.5 GiB free. No heavy job is admitted. Follow
the repository watchdog and durable-evidence requirements before running any
future native qualification. Sending the current status to the parent chat was
refused by the tool because it requires approval while its approval policy is
`never`; the status remains available in this worktree.
