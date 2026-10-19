# Package overlap cleanup: local qualification

Eight scoped fixes are merged in PRs [128](https://github.com/civictechdc/congressional-tech/pull/128),
[129](https://github.com/civictechdc/congressional-tech/pull/129), and
[130](https://github.com/civictechdc/congressional-tech/pull/130). Independent
reviewers approved each exact implementation before merge. The combined code
revision is `f438264f791956abd37177e9d334d00eb010e169`.

## What changed for users and maintainers

| Change | Benefit and preservation evidence |
| --- | --- |
| Browser retry pins its accepted catalog | A worker restart cannot switch data underneath existing filters/details. Explicit selection, stale replies and cancellation stay intact. |
| Existing file/reference proofs survive local handoffs | Unchanged issued files avoid another SHA pass; plain restored facts rehash and changed custody refuses. Direct local publication validates references once instead of twice. |
| Catalog reader ownership is explicit | Both readers close on success and partial acquisition/schema/reference failures. Cleanup failures preserve the original refusal. The unused filename-only selection route is removed. |
| Failure/status/receipt ownership is corrected | Terminal HTTP errors close; unbound local attempts expose bounded uncertainty without accepted-output authority; restored phase files stay inside their attempt; proposed selectors stay distinct until verified commit. |
| Retained-data rules have one owner | Three consumers share body-key digest/shard parsing. GPO delegates atomic CSV writing while preserving sort timing, exact bytes and failure cleanup. |

The gains add up as removed work and fewer places to maintain a rule. Real fixture
handoffs remove 26 repeated SHA bytes on read-to-retain and 1,052 on
snapshot-to-history; the same serialized facts still hash those bytes. These
small fixtures establish the eliminated pass, not production bytes saved. Direct
local publication removes one of two complete reference checks. No aggregate
wall-time or full-catalog memory improvement is claimed from these tests.

## Local checks

- Maintained `production-offline` suite: **9,447 passed and 38 subtests passed**;
  50 loopback tests excluded by the declared lane. Five dependency SyntaxWarnings
  remain. Command: `.venv/bin/python scripts/dev.py test production-offline`.
  Pytest reported 275.24 seconds; the recorded command interval was 280.87 seconds.
- Browser/package lane: 104 JavaScript checks, 88 body-key/evidence checks and
  25 CSV/GPO checks; a 29-page local build and two emitted-bootstrap scenarios.
  Final frozen offline install used Node 22.22.2 and declared npm 11.19.1 with
  unchanged lock bytes. These counts overlap the integrated Python suite.
- Storage lane: 166 focused local checks. Control suites: 73, 60, and 39 checks
  plus five subtests, with overlap between focused selections.
- Integration matched all 23 changed non-ticket file comparisons to their
  reviewed sources. The two independent `document_index.py` changes matched
  their reviewed function bodies; removed helper remained absent.

Local checks are the merge gate requested by the user. No CI result, new source
acquisition, held-out classification, full-catalog build, live browser journey,
production mutation or resource-limit change is claimed by this qualification.
Historical hosted/live evidence remains separately pinned.

## Grades and next priorities

All **168 original entries** are reassessed: 116 resolved, 30 intentional
tradeoffs, 20 partial and two unresolved. Eleven narrow updates reflect this
batch. Twenty-three entries retain explicit actions, and measured resource/policy
follow-ups bring the mapped open-work coverage to 34 entries across twelve tickets.
The [complete report](package-overlap-rescore-20261019.md) preserves function
scores and evidence; the architecture synthesis remains **B- overall**.

Per the user's direction, efficiency and architectural debt lead the backlog:
repeated mapping/checkpoint work (`ct-2uwd`, `ct-v6ao`), Catalog memory (`ct-m9ry`),
broad-search cost (`ct-4zer`), and explicit runtime/accepted-plan ownership
(`ct-piku`, `ct-bpyj`). These are priority 1; dependencies preserve implementation
order. Measure comparable work/resource costs and avoid adding overlapping timing
percentages. The other six tickets retain resource-policy and operator-diagnostic
work. All findings have a ticket or an explicit keep decision; no duplicate task
was created merely to force a grade above B+.

## Integration and preservation

The evidence/ticket change records **65 closed, 12 open and zero in-progress**
tickets. The eight implementation tickets are closed; follow-ups remain open.
Three implementation worktrees are archived. The final evidence worktree is
archived after its reviewed evidence PR merges; the primary output directory
will retain the final completion and cleanup receipt after that merge and archive.

The user confirmed concurrent Grok/Cursor refactoring of `/scripts` in the primary
checkout. Its separate local commit `e0d7df3` and subsequent work are outside this
qualification and remain untouched. Do not reset, push or synchronize that checkout
as part of this batch. Preserve the unrelated `pipeline-data` worktree and
`codex/publication-local-history-20261018` branch.

The [evidence index](package-overlap-evidence-20261019.json) records byte counts and
SHA-256 hashes for retained local receipts, reviews, gradebook and test log. Raw
logs and historical before/after evidence remain under
`output/package-overlap-rescore-20261019/` in the primary checkout.
