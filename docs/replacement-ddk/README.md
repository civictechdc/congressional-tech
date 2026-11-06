# Congressional-tech DDK replacement

The replacement is in progress in this isolated worktree. Source/consumer
inventory and independent reviews are recorded; review corrections and the first
definition-authority implementation are underway. **No end-to-end replacement
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

`uv sync --frozen` and the required local ticket index refresh completed. No
replacement Python lane, browser suite or native job has run yet. The disk fell
from 37 GiB to 8.7 GiB locally, then the parent reported 7.7 GiB. No heavy job is
admitted. Follow the repository watchdog and durable-evidence requirements before
running any future native qualification.
