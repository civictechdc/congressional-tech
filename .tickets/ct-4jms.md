---
id: ct-4jms
status: open
deps: []
links: [cefr-xjsp, cef-96wc, ct-tk10, ct-ud0b, ct-1l1h, ct-98sm, ct-v967, ct-rie2, ct-5kto, ct-082q, ct-hiec]
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, ops, capture, cutover, track5]
---

# Verify scheduled capture against the current archive release

Keep the archive fresh by running the existing capture workflow against the selected release's URL state. Local writer and scheduler evidence already exists. The open step is a successful scheduled production run with inspectable target outcomes.

## Root cause and unresolved boundary (2026-11-05)

November 5 read-only inspection found `capture-archive.yml` (workflow 399669501) `disabled_manually` with zero recorded runs. The visible repository variable list contains only `CLOUDFLARE_ACCOUNT_ID` and `DOCSPEC_RUNTIME_ARTIFACT`. The environment inventory omits `archive-capture`, and its exact lookup returned 404. Organization-variable access returned 403, so inherited effective values remain unknown. The workflow requires an enable value, a selected pointer and three positive budgets. The reason for disabling and private credentials were not established. Passing local selection tests or publishing e145 does not establish scheduled acquisition.

The concrete Ashley Nunes target is `https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1`. Discovery already found that link. The base address saved an HTTP 200 HTML wrapper (`is_real_file=false`, body `ae5ee73d95a8fada1e9491574799cf263d03114d3f84d830ed26a9f6e1e0934c`); selected inputs contain no file capture/recovery, and the download target has zero attempts in e145. The first missing handoff is discovered target to file acquisition. No invocation, budget cutoff, refusal and attempted failure remain distinct possibilities until the exact queue/receipt trace is read.

Ordinary capture supports profile version 1. Explicit recovery campaigns require a separate version-2 requirements-bound input. Failure due dates follow the existing family/age retry policy; their presence alone is not a demonstrated retry defect.

The current command supplies neither a cutoff URL list nor the weekly seed inputs described in `raw-source-tables.md`. Its starting queue is the selected release URL state, followed by in-run discovery. Correct that documentation or explicitly bind a demonstrated input need; do not restore the obsolete weekly path by default. An exception after remote receipt acknowledgment but before the local completion marker can omit a durable receipt from the summary. The workflow's top-level JSON glob also misses nested failure summaries. These are reporting gaps, not demonstrated lost raw objects.

## Acceptance Criteria

- Recheck workflow state, applicable variable scopes and cutover prerequisites. Enable the existing workflow and `ARCHIVE_CAPTURE_ENABLED` binding at cutover; record one successful scheduled `capture-archive.yml` invocation, run ID, source revision, exact release/profile/URL-state identity, budgets and emitted receipt keys. A manual dispatch or restored schedule alone does not meet scheduled-run acceptance.
- Verify creating receipt lines record `stored_md5` and `stored_suffix` against acknowledged stored objects. Prove receipt-referenced bodies exist and the run reads no old index. Account for each selected/cutoff target with an attempt receipt, retained result or explicit reason; preserve the observed target and repaired candidate addresses separately.
- Trace the exact Ashley base and download targets through discovery, due queue, eligibility/cutoff, attempted candidate and receipt. Run the admitted bounded attempt or record a supported refusal/exclusion; an unexplained zero-attempt target is not complete. A remote failure remains a failure with its retry/next-action disposition, not a downloaded document. If content is acquired, verify body qualification and the intended testimony relationship; hand any required alternative recovery to ct-umtm with the same locators.
- On the first run of a merged raw-writer change, compare prior raw key, size and ETag preservation with the documented B0 exception. Retain reconciliation and raw verification evidence under the [switch plan](../docs/plans/engine-first-switch.md). The Mac nightly publisher implementation is complete under ct-ud0b; cef-96wc owns its remaining scheduled publication acceptance. Raw lock/readback remains with ct-1l1h.
- Demonstrate the existing ordinary-capture policy without weakening campaign guards. Attribute any proposed retry change to an actual repeated-request history and violated or explicitly revised policy; do not mark every failed address terminal. Keep campaign execution and publication gains out of this ticket's success claim.

- Bind reviewed target accountability through the existing `--cutoff-urls` input where needed. Retain attempt, retained-result and refusal reasons, including terminal failures. Upload the nested run summary when the top-level call raises. Preserve acknowledged receipt keys even if later discovery or local completion recording fails; use existing receipt and run records rather than adding another tracking system.

## Evidence

[November 5 root-cause analysis](../docs/experiments/url-normalization-revalidation-20261105/root-causes.md); exact GitHub commands in `.cache/archive-release/investigations/url-root-cause-20261105/greybeard.md`; Ashley capture and live queries in `.cache/archive-release/investigations/url-root-cause-20261105/etl-recovery-campaign/{handoff-check.json,mcp-ashley.json}`. The retained discovery result is `docs/experiments/url-normalization-validation-20261031/evidence/discovery-link-results.json`. These are November 5 observations, not proof of future deployment state.

[Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

## Notes

**2026-11-01T20:08:14Z**

Reopened 2026-11-01: capture-archive.yml is disabled_manually with no recorded runs, and ARCHIVE_CAPTURE_ENABLED is not set. Acceptance requires a live run.

**2026-11-05T17:11:15Z**

Acceptance transferred from ct-v967/ct-98sm: record the successful scheduled capture-archive.yml run against the exact selected live url_state.parquet identity, run ID and emitted receipts. For creating lines, verify stored suffix and MD5 against the acknowledged object and prove every referenced body exists; confirm zero old-index reads. For the first run of a merged raw-writer change, compare prior raw key/size/ETag preservation, retaining the documented B0 exception. Preserve the accepted-map reconciliation evidence and the actual raw verifier result; do not claim a restored schedule proves an unattended invocation. ct-1l1h separately owns lock/readback and weekly verification after locking.

**2026-11-05T20:18:16Z**

Applied the accepted third-round scope update. The current description records the root cause, delivered work, remaining behavior and bounded checks; historical notes remain unchanged. No implementation or operational action was performed. [Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

**2026-11-05T21:22:04Z**

The reporting fixes are locally committed and independently reviewed in `5dc11c197b1a9cf719810d0a834dfe2c9acce6b9`. The release owner has the commit for integration. The workflow can bind an optional owner-reviewed JSON URL list through `ARCHIVE_CAPTURE_CUTOFF_URLS` and `--cutoff-urls`. The capture queue starts from the selected release's URL state and follows in-run discovery. The artifact allowlist includes the nested scheduler summary after a failed CLI run. Reports preserve reviewed and attempted addresses separately, identify retained or refused targets, and keep acknowledged receipt keys through discovery or local completion failures and another failed continuation.

The pinned runtime and Poppler 26.06 passed 148 tests across four capture test files. These are focused local results. The receipt writer owner has the separate first-upload scratch cleanup case, where an exception after storage can prevent acknowledgment from reaching the scheduler. [Lane status](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/capture-ops/STATUS.md) · [Focused test log](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/capture-ops/capture-final.log)

Live acceptance remains open. At cutover, verify the effective workflow bindings and record a successful scheduled invocation with its release, profile, URL-state identity, budgets and emitted keys. Preserve the live Ashley base, observed download and repaired candidate trace through the queue and receipt or supported disposition. Verify stored MD5 and suffix, receipt-referenced body existence, zero old-index reads, and first-run key, size and ETag preservation with the documented B0 exception. The production hold remains in force.

**2026-11-05T21:31:58Z**

Integrated local follow-up at `5ab813f919484c5d994d52220d898b2f69ea1257` combines receipt cleanup fix `8cda71d5` with scheduler acknowledgment change `5dc11c19`. The stable writer completes scratch cleanup before uploading the frozen receipt. A planted cleanup error at the writer boundary left no uploaded receipt, and retry used the original key and bytes. The writer and scheduler files passed 114 focused checks. All three targeted scheduler acknowledgment cases passed. Prepared-only receipts stay out of the summary, while keys acknowledged before discovery or local completion fails survive a repeated failure. Retry clears the pending entry without another source request. Independent review confirmed the exact revision, local bytes and test results. The scheduled production run and its live evidence remain open. [Integrated test log](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/integrated-composition.log) · [Acknowledgment checks](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/integrated-acknowledgment.log)

**2026-11-05T23:06:22Z**

The final acceptance probe reproduced a cutoff reporting error on unchanged `f1ee8fe3`. A reviewed `report.pdf%20` had a due HTTP 404, and the repaired `report.pdf` had its own HTTP 503 and a future retry date. The scheduler correctly emitted no request. The report used the old address and returned `queue_empty` with the stale 404 and past date.

The isolated correction uses the exact repaired address's state when it governs the cutoff. The same case now reports `deferred / not_due` with the repaired address's 503 and future date. The cutoff report regression covers both cached and uncached URL state. Eight focused local checks passed, including same-key retry and existing campaign and cache controls. The failure and repair checks are retained in the Wave 3 acceptance-final `capture-ops/cross-key-repair` evidence directory.

Scheduled acceptance remains open. Verify the live release and workflow bindings, the scheduled run and artifacts, the Ashley queue and receipt trace or supported disposition, receipt-referenced body existence and stored pins, zero old-index reads, and first-run key, size and ETag preservation with the historical B0 exception.

**2026-11-06T16:46:48Z**

November 6 read-only provider verification still leaves scheduled production acceptance open. At 16:36–16:40 UTC, workflow 399669501 is disabled_manually; both all-event and event=schedule inventories contain zero runs. There is no scheduled queue, cutoff/refusal/failure result or receipt to inspect. Remote main remains c3ee2eec686ebcfe77140840b6c2f5fcc3a7bcbf and its workflow still omits the locally completed reviewed-cutoff and nested-summary fixes. Do not recreate those fixes or count their local tests as deployed acceptance.

Visible repository variables still contain only the account and runtime artifact. The archive-capture environment and its variable/secret inventories return 404. Repository secret names omit ARCHIVE_CAPTURE_R2_ACCESS_KEY_ID and ARCHIVE_CAPTURE_R2_SECRET_ACCESS_KEY; the generic R2 names do not satisfy those workflow references. Organization variable and secret-name access both return 403, so inherited effective values remain unknown. Credential values/usability were not tested.

The fresh public pointer and manifest still select e145d24c389e43e05a0bcb3f71cd1f75ee919a066dfa810f0ba39a16283d4a99, with the same manifest SHA-256 and url_state pin as the retained Ashley audit. The base remains a retained HTTP 200 HTML wrapper; discovery records the exact &download=1 address, while ?download=1 is the separate repaired candidate. The retained audit reports zero file-target attempts; this session made no queue scan or source request and does not infer a cutoff, refusal or remote failure from non-execution. Eight relevant local source/test/runtime-pin files match reviewed repair 81a1d41e, so its existing 13-pass focused acceptance is credited within that partial local scope.

Fresh raw GET responses, exact hashes, source reuse checks, an unbound proposed cutoff list, and precise owner cutover steps are retained in [readback](../.cache/archive-release/implementation/reviewed-non-news-20261106/ct-4jms/READBACK.md) and [machine-readable result](../.cache/archive-release/implementation/reviewed-non-news-20261106/ct-4jms/readback.json). No new source repair was demonstrated. The release/cutover owner must integrate the completed fixes, reconcile bindings and admitted budgets, then retain the first actual scheduled run and Ashley/receipt/body/preservation evidence. No dispatch, scheduler change, import, publication or deployment occurred; ticket remains open.

**2026-11-06T18:43:09Z**

Independent read-only work is complete; ticket-evidence commit `f9aa5828aa4fffe0891fb3996b15ffadb9d7878f` remains preserved. November 6 18:22 UTC readback shows the workflow disabled manually, zero recorded runs and e145 still selected. No scheduled Ashley queue/receipt outcome exists to inspect; retained wrapper, observed download and repaired candidate remain distinct. Independent GPT-6.1 Sol/xhigh reviewer `/root/ct4jms_independent_review`, after reading all four requested skills, APPROVED this evidence-only update with high confidence. It verified 17 retained GitHub responses, release/input identities, eight relevant source/test/pin files and dependency manifests; it credited the retained 13-pass partial result without rerunning tests. No material defect or source repair was identified. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-4jms/REVIEW.md) · [Handoff](../.cache/archive-release/implementation/reviewed-non-news-20261106/ct-4jms/HANDOFF.md).

Keep open: the missing invocation-to-attempt boundary is documented, not resolved. Original root owns integration; ct-m104 and the coordinated production operator own final release and admitted scheduler cutover. Once an actual scheduled event exists, ct-4jms must verify Ashley dispositions, receipts, body pins/existence and first-run preservation; ct-1l1h retains separate raw-lock evidence. The proposed cutoff list alone does not prove an admitted attempt.

Independent review: APPROVE for the scoped work; remaining ticket acceptance is unchanged. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-4jms/REVIEW.md).

**2026-11-08T17:28:23Z**

2026-11-08: the planner could not plan the live release (Resources exhausted on 1.2M url_state rows, then a refusal for two unkeyable historical addresses). Fixed on claude/sweep-c (b3ababac): url_state-sized steps read more than once are materialized; '' and 'http://File URL path: ...' are counted as unkeyable_states and never scheduled. Dry run on 630164505301 under the standard limits: exit 0, 629,541 due, 2,000 queued, 11 s, 3.3 GiB peak RSS; identical queue to the old code on a 300k-row subset. Still open: the first scheduled run and its receipt checks. Ashley's &download=1 target is due (attempts 0) but sorts alphabetically outside the first 2,000; a --cutoff-urls entry does not move an unattempted URL ahead.
