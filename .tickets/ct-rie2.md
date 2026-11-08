---
id: ct-rie2
status: closed
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

**2026-11-06T18:43:10Z**

Prepared the one-target USAID/ecoi recovery cohort and committed catalog attribution, separate initial/final progress reporting and body-free retry in a04ee550/edff4588. Repair 4e11106f now binds every acknowledged decision field and receipt/provenance key to original request/evidence and frozen receipt metadata; both consumers reject duplicate fields. All 50 focused checks passed (partial lane); exact code/log pins are in ct-rie2/f1-repair/checks.json. Independent four-skill review is running against this exact commit.

Root owns source integration and final review; ct-m104/the designated shared writer owns actual version-2 inputs, supported capture admission, timestamped receipt/import, final release and reader/MCP verification. No real cohort capture/import/publication occurred here; retain in_progress.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at 4e11106f. Recovery retries and progress reports now bind the complete original decision, request and frozen receipt/provenance identities. Duplicate fields are rejected, while retries remain body-free. All 50 focused checks passed and the repaired source received independent approval.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Actual version-2 cohort execution, supported capture admission, timestamped receipt/import, final publication and reader/MCP attachment checks. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-rie2/REVIEW.md).

**2026-11-07T22:30:56Z**

November 7 post-release owner update for archive 5d24699ad9fa / Explorer 0.6.2. The selected release has no USAID/ecoi cohort attachment. Current version 1 refuses the campaign; the bounded version 2 preflight admits exactly the proposed mirror and preserves the target address. Missing eligibility and mismatched requirements refuse before work. Installed and hosted readers retain the two homepage notices. No request, import or publication was performed by this preflight.

Keep in_progress. Root must admit the concrete one-target version 2 operation, check for an existing acknowledgement/complete receipt, and execute the bounded capture/import once if absent. Preserve the original descriptor on retries and both homepage null successors. Closure needs the verified selected attachment or a supported final nonpublication decision; the private queue proof is not execution. [Owner evidence](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-rie2/STATUS.json).

**2026-11-07T22:54:53Z**

November 7 execution completed for the single USAID/ecoi fact sheet. The maintained scheduler captured one complete HTTP 200 response: 361,013 bytes, matching the previously qualified PDF. The maintained importer accepted operation 21ebd7b7c5c6726d42f4de69ba0065ea3a565b5992eaeafce15fb6f3b27480db and appended its receipt and source attribution to shared raw storage. Both remote objects were confirmed; replay returned the identical acknowledgement without R2 credentials. The capture and import used 0.29 GiB and 0.16 GiB peak RSS respectively.

Keep in_progress for selected-release integration and actual reader attachment. The public release remains 5d24699ad9fa. Preserve both retired homepage null successors, the original descriptor and request, and the distinction between recovered requested content and historical byte identity. No further acquisition is needed for this target. [Execution result](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-rie2/writer-run/ROOT-RESULT.json).

**2026-11-07T23:26:52Z**

November 7: integrated the reviewed scoped recovery append at b0c980f1. It admits one accepted capture and at most its one filename row, checks their producer versions and keys before writing, and recovers an interrupted append only when the current table contains the exact staged addition. Unchanged meeting, appearance and Explorer selections retain their parser versions. This prepares the recovered USAID fact sheet for selection without processing unrelated pending work.

Independent four-skill source and caller review approved the final commit. Three focused default-daily regressions passed (partial production-offline selection, not a full lane). The private native check passed lost-response recovery, one-time filename append, an unchanged retry, wrong-key/version refusals, unchanged unrelated pending work and unreadable records, and retained entity selectors/version maps. Peak RSS was 0.539 GiB for regressions and 0.47 GiB for the private probe. Root verified all 21 frozen input/source/evidence pins. Sniff and body-reading implementation did not change; their declared versions remain equivalent for this append-only path, supported by the bounded controls.

Keep in_progress. Shared lake execution and public attachment have not occurred; archive 5d24699ad9fa remains selected. Before execution, check live writer/collector exclusion, exact heads and provenance, and production memory/disk admission. Publication still needs the explicit recovery cause, source attachment and authored-note readback through MCP/site, and both null-successor controls. Evidence: .cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-rie2/scoped-selection-b0c980f1/ .

**2026-11-07T23:40:54Z**

November 7: the reviewed one-receipt lake update completed from main 88e2deee. Native before/after checks found exactly one added capture and one added filename row, with no extra or missing values. The captures snapshot is now 3703623901182761760; filename readings is 331637886293973332. Body readings, entity selections and their parser versions stayed unchanged. The complete receipt list grew from 24,341 to 24,342 by the single acknowledged recovery receipt, and both moved tables have producer records.

The guarded attempt finished in 114.6 seconds with 2.056 GiB peak RSS and 1.727 GiB charged physical memory; final free disk was 74.3 GiB. The shared writer lock was released. The run used a separate frozen runtime and an 8 GiB scratch cap, with no new acquisition or body-reading work. This is the measured scoped selection result, not full-build sizing.

Keep in_progress. Public archive 5d24699ad9fa is unchanged. The next coordinated release must build from the prepared inputs, qualify the recovery's explicit cause, and verify the actual target/body attachment and authored explanation through MCP and the site, preserving both null-successor controls. No full model build or publication ran. Prepared model: .cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-rie2/selection-execution-20261107/work/model-spec.json (SHA-256 537e32fd7c993da44722f6830686434c9424e66ee1576ae5cc97e233c1645157). The same directory retains append-result.json and receipt-keys.json; sibling logs retain the command, watchdog report and resource timeline.

**2026-11-07T23:48:03Z**

Independent readback approved the completed shared selection: exact accepted source/body binding, one capture and one filename addition, complete prior receipt retention, unchanged unrelated selectors and unreadable records, and matching producer acknowledgments. The selected inputs remain reusable.

Merged follow-up 394fb9dd separates native append and validation result directories. The baseline reproduced the overwritten result; focused private native normal/retry controls preserved both results and remained idempotent. The one-line change passed independent review. No shared append, acquisition, default suite or full build was repeated. Keep in_progress for candidate/public acceptance. [Focused evidence](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-rie2/append-artifact-path-394fb9dd/EVIDENCE.json).

**2026-11-08T15:26:16Z**

2026-11-08: published in archive release 63016450530114d8ebc03d2936dc8293250ffd546bf00d5205909345216e5e78 (public pointer moved; browser contract and public canary passed; hosted Explorer re-pinned in aed605d1 and read back). Causes: model/jobs/release-causes/5d24699ad9fa-630164505301.json; note: docs/releases/2026-11-08-630164505301.md. The USAID recovery (decision 21ebd7b7, body dd7d7f35, 361,013 bytes) is published with url_state capture_* columns.

**2026-11-08T17:28:03Z**

2026-11-08: closed. Release 630164505301 publishes the one-target cohort: Gate 1 cause row adds exactly 1 document/link/lookup key (decision 21ebd7b7, body dd7d7f35, 361,013 bytes), none removed; hosted MCP and site return the attachment with its authored note (ct-nh41 checker passed); hosted get_document still returns removal notices for retired homepage keys 5c1767950ecb2bdc and 0bf90c57369641ee (null successors kept). Resource use is in the Nov 7 notes. For a one-target cohort the release comparison is the final count reconciliation; semantic equivalence to the historical original stays unknown, as the note says.
