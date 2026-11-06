---
id: ct-rie2
status: in_progress
deps: []
links: [ct-umtm, ct-4jms, ct-nh41, ct-aapl, ct-tk10]
created: 2026-11-05T20:08:13Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [recovery, campaign, ops, publication, url-audit]
---
# Recover and publish one useful document cohort

Recover a bounded set of useful documents and make the accepted results accessible through the archive and MCP. Share a real cohort and execution with `ct-umtm` where its per-target work fits. Recovery candidate-selection code is implemented, but e145 does not establish production acceptance of the separate version-2 campaign path. Its selected model has no recovery requirements and emits valid ordinary-capture profile version 1. ct-4jms owns ordinary scheduled capture; it cannot close this campaign-specific acceptance.

## Root cause and reporting boundary

`archive_model.py`/`archive_profile.py` emit version 2 only when recovery requirements are selected. `capture_scheduler.py` deliberately refuses campaign execution without version 2, matching requirement pins and explicit eligibility columns. No such campaign inputs or execution results are selected in the audited release. This is an input/execution gap, not a broken version-1 serializer.

`run_recovery_campaign` returns its initial plan/counts even after optional imports. Those counts do not establish final accepted or published progress. The existing per-target ledger, import operation records and release comparison already provide the necessary owners; their results need to be joined and final state replanned. Import idempotency binds both the original descriptor and request digests. A final-state report must not replace those execution bindings.

[November 5 root-cause analysis](../docs/experiments/url-normalization-revalidation-20261105/root-causes.md). Evidence: `.cache/archive-release/investigations/url-root-cause-20261105/etl-recovery-campaign/{report.md,selected-recovery-input-check.json,evidence-pins.json}`. The twelve Wayback target/body dispositions belong to ct-umtm, and explanation authoring belongs to ct-nh41.

## Design

Choose one bounded real cohort from existing recovery work and state its intended requirement (`historical_exact`, `requested_content`, or `current_official_counterpart`) and refresh policy. Reuse qualified retained bodies and completed stages where exact pins/custody still hold. Bind the descriptor, membership, candidates, requirements and selected state/profile; use the existing capture/import and release paths.

Ordinary scheduled capture and explicit campaign execution are independent acceptance steps, not artificial dependencies. Preserve version-1 support and all version-2 refusal/suppression guards. This ticket defines a future execution finish condition; updating it does not enable workflows, dispatch requests or publish data.

## Acceptance Criteria

- Retain one bounded real cohort descriptor with membership, candidate, requirement, policy, source/state/profile and engine pins. Produce/select the version-2 profile and explicit eligibility fields through the maintained model; record the actual campaign input identity separately from the current public pointer if they differ.
- Show version-1 campaign input, missing eligibility columns and mismatched requirement pins refuse before acquisition or writes, while ordinary version-1 capture remains supported. Qualify eligible, accepted-and-satisfied, excluded, unresolved and refresh-live cases with retained controls. The actual bounded run attempts only admitted unsatisfied work and preserves target versus candidate addresses and prior history.
- Record the real run/operation IDs, budgets, queue/cutoff disposition, candidate receipts, qualification/acceptance records and acknowledged import receipt/provenance keys. Account for every cohort target including refusals and failures. Resume or rerun evidence must show completed accepted work is not reacquired merely because planning restarts.
- Follow each accepted import into the selected capture/provenance inputs and the maintained publication gate, retaining source identity and relationship. Verify the intended public target/body attachment through both MCP and the reader on the selected release, or record a supported non-publication disposition. Local tests or a successful ordinary schedule alone cannot close this ticket.
- Preserve the original descriptor, request digests and acknowledged import bindings through retries. Produce a separate read-only final plan from updated state after acknowledged imports; do not feed its changed descriptor back into the original import operation. Join the final plan to the base/candidate release comparison. Reconcile target counts, distinct qualified bodies, accepted target/body relationships, imports, attached occurrences, distinct document rows and newly verified semantic-document gains with explicit units and pins. Keep initial counts labeled initial; unknown semantic equivalence stays unknown. Do not add accepted-target totals or reuse counts to claim publication gains.
- Reuse the existing per-target ledger and release gates. Report the bounded run's request/byte/spool use, elapsed time and peak memory; justify any further acquisition/recompute by a named unresolved input. Preserve legacy recovery records and public lookup/link continuity.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).

## Notes

**2026-11-05T20:56:46Z**

Final root-cause review: deliver one useful bounded cohort through the archive and MCP. Share ct-umtm execution where suitable; keep original import bindings on retry and produce final counts from a separate read-only plan.

**2026-11-06T17:57:29Z**

Isolated implementation committed as a04ee550afc55a58b9c280619c5f7c48e738a544 on codex/ct-rie2-recovery-report-20261106. Descriptor preparation now refuses changed existing inputs, explicit resume preserves original execution/request bindings without rediscovery, and validated accepted acknowledgements replay the original decision/receipt/provenance without body/source reopening or requalification. Counts are labeled initial. New read-only progress reporting joins the existing initial/final ledgers and import operations, accepts ct-nh41 note-policy bindings, and links the maintained base/candidate comparison without claiming publication or semantic gains.

Added request-bound source_catalog_document_identifier plus registry/fixture support; the legacy default remains unchanged. This supplies truthful ecoi attribution without rewriting old requests or touching ct-nh41 explanation authoring. Independent GPT-6.1 Sol xhigh advice confirmed the narrow compatibility path.

Reused ct-umtm 81eb31ca's one-target USAID/ecoi 2074278 requested_content/historical_only cohort, plus ct-nh41 59d0d063's supported explanation fragment. Original prepared descriptor digest c37d52811127cb2ffb93c593e40c70b2211d2c365029fe0089c78b97f6b131fe; no actual version-2 execution descriptor/state/profile is selected yet. Read-only native plan/report: 1 retained_candidate_pending target, 0 acknowledged imports. Shared body/qualification/source evidence stays in place. The pending request intentionally has no receipt/decision and is not importable.

Verification on the code commit: own uv sync --frozen, pinned local runtime and Poppler 26.06.0; 105 passed, production-offline partial 7 of 500 lane files, exit 0; 0.56 GiB peak RSS under watchdog. Includes ordinary v1 scheduling, v1/missing-eligibility/mismatched-requirements campaign refusals, maintained v2 model/refresh controls, legacy/catalog retries, interrupted/rejected reporting, false-ack refusal and registry precedence. No full lane or production acceptance claimed.

Precise remaining shared actions: integrate ct-umtm/ct-nh41 and this patch; select actual v2 inputs and freeze the actual execution descriptor; qualify a supported exact-candidate capture route (current scheduler positive scope matches neither USAID target nor ecoi mirror, and this patch does not widen it); obtain one complete timestamped receipt capped at 361014 body bytes; import once through the single writer with original bindings; select receipt/provenance, compare the releases and verify exact target/body attachment through reader and MCP. Keep retired homepage keys 5c1767950ecb2bdc and 0bf90c57369641ee with null successors. Unknown semantic equivalence stays unknown. Ticket remains in progress.

Durable status, bounded inputs, read-only helpers, scope check, tests and HANDOFF.md: .cache/archive-release/implementation/reviewed-non-news-20261106/ct-rie2/. No candidate acquisition, shared raw/catalog import, full-corpus model/replay, publication, pointer flip, scheduler change, merge, push, deployment or cleanup occurred.
