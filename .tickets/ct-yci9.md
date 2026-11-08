---
id: ct-yci9
status: in_progress
deps: []
links: [ct-flg9, ct-j9o7, ct-aapl, ct-tk10]
created: 2026-11-05T20:08:12Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, document-identity, publication, url-audit]
---
# Correct bill associations when source filenames agree but the document contradicts them

Readers currently receive the wrong bill association for public document `f984b8439d21b0ef`. Its exact body `f984b8439d21b0ef80f8a6f2e16f1dfc20d1ff57a53afe3f65ceefca67b551ee` says H.R. 4755, Privacy Enhancing Technology Research Act, while e145 publishes `BILLS-118hr4775ih` and `118-hr-4775`. Both Congress.gov and docs.house.gov source filenames say `BILLS-118HR4775ih.pdf`.

## Root cause

`source-annotations-final.sql` correctly records the source filename claims. `document-packages.sql` only catches disagreements among filename-derived bill candidates, so two agreeing wrong names pass. `document-metadata.sql` independently unions filename-derived `measure_keys`, leaving a second wrong association even if package selection is cleared. The recovery bill checker is not on the original-capture path. The current policy lacks an explicit disposition that withholds an unsupported package and direct measure. The merged positive-only `bill-package-evidence.json` input qualifies a different exact H.R. 2899 PDF under `ct-j9o7`; it does not resolve this case. `document-normalized.sql` can also refill a null package from `recovered_copy_fills`. This is not a filename parsing or reader formatting error.

[November 5 root-cause analysis](../docs/experiments/url-normalization-revalidation-20261105/root-causes.md). Exact PDF and probe evidence: `.cache/archive-release/investigations/url-root-cause-20261105/etl-identity-lookup/{REPORT.md,probe-results.json,live-mcp.json}`. Source inspected at c3ee2eec; release e145d24c389e. ct-flg9's closed disagreeing-filenames repair and ct-j9o7's missing-type recovery address different cases.

## Design

Owner: document package and direct measure selection. Choose the smallest maintained, evidence-bound decision path for the demonstrated body/component. Reuse the maintained PDF evidence input pattern where appropriate, but add explicit withholding and direct-measure dispositions; the current positive package entry is not such a configuration toggle. Preserve literal source claims and public body identity. Reuse retained captures and filename readings; limit semantic recomputation to affected components and downstream metadata. Shared export costs must be measured separately.

Do not apply the recovery helper wholesale to ordinary originals: first-page references to multiple bills and unnumbered drafts can be flagged, while the helper alone does not establish Congress or package version. Do not hide the entire document or hard-code a replacement package in the reader.

## Acceptance Criteria

- Retain a body-bound adjudication with the actual cover/text and source locators. The exact demonstrated document no longer asserts unsupported `BILLS-118hr4775ih` or direct measure `118-hr-4775`. Check both paths independently through final model output; `recovered_copy_fills` must not restore the withheld package.
- Preserve its bytes, both source URLs, captured filename, source annotation claims, body/link keys and availability. Assert a 118-H.R.4755 relationship only with an explicit supported decision; keep package identity unresolved unless the exact package version is independently established. Do not infer `4755ih` from the bill number.
- Use bounded controls for agreeing wrong filenames, disagreeing filenames, stronger authoritative package evidence, same-bill editions, an unnumbered draft, a page mentioning another bill and a different Congress with the same number. A body mention alone must not override an unrelated document's identity. Independent evidence must detect a planted wrong association.
- Verify the owning model outputs and maintained release checks, including source preservation and cause attribution. Through the selected public release, MCP document detail, bill-entity document lookup and actual site search agree on the corrected associations; recovery unit tests alone do not meet acceptance. Distinguish direct document identity from independently supported meeting-context bill relationships. If 4775 remains visible, identify its basis before removing a legitimate contextual link.
- Record the exact affected subset and unsupported/unresolved cases. Start with this one body/two-source counterexample and already-adjudicated contradictions; no global PDF scan or parser-version change is required merely to fix it.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).

## Notes

**2026-11-05T20:56:46Z**

Final root-cause review: withhold unsupported package and direct-measure claims through final normalization, including recovered-copy fills. Distinguish direct identity from supported meeting context. Existing positive-only package evidence does not settle this case.

**2026-11-06T17:28:32Z**

Implemented and locally qualified in task-owned branch codex/ct-yci9-bill-adjudication-20261106 (integration commit recorded in durable HANDOFF.md). Extended the maintained bill-package PDF evidence input with explicit dispositions and the exact f984b8439d21b0ef80f8a6f2e16f1dfc20d1ff57a53afe3f65ceefca67b551ee body plus both observed source locators. Package selection and final recovered-copy fallback withhold identity; direct measures remove only 118-hr-4775 and explicitly support 118-hr-4755. No edition is inferred. Source filenames/readings/annotations, source membership, bytes, body/link keys, availability and legitimate meeting-context claims remain intact.

A shared small materialized decision relation owns this behavior; model evidence records its id and rationale. Final model invariants enforce its package/direct-measure dispositions. Recovery preservation checks exempt only the named rejected package/measure claims and still detect unrelated lost claims.

Focused production-offline check passed: 17 tests across test_bill_identity_decisions.py, test_phase1_document_metadata.py and test_recovered_copy_merge.py (partial selection, not a full lane). Exact retained PDF ran through the unmodified native model/export and all six invariant suites. An injected wrong recovered-copy fill produced the same corrected release identity. Source preservation, positive PDF evidence, authoritative package precedence/explicit edition hold, disagreeing filenames, same-bill editions, distinct bytes/source/Congress/rendition/draft/reference bindings, unrelated direct measures and narrow recovery loss checks passed. Pinned cause evidence passed load_causes and require_release_gates. An independent GPT-6.1 Sol xhigh reviewer executed the PDF-cover check and confirmed separate old-package/old-measure, invented-edition and wrong-Congress plants are detected.

Evidence: /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/implementation/reviewed-non-news-20261106/ct-yci9/ (focused-final.log, watchdog-final.json, pytest-final, STATUS.md and HANDOFF.md). Final watchdog peak 0.52 GiB RSS; no corpus scan or parser-version change. Doctor's workspace-only sniff/readings drift had matching fixed samples; this patch changes document selection only and accepts those retained reading versions unchanged within this scope.

Ticket remains in_progress: coordinator integration, selected release publication, final MCP document detail/bill-entity lookup and actual site search acceptance are not performed by this session. Retained e145 meeting 115732 includes 4775 among seven subjects; its raw source basis is not established by that derived row alone. Preserve independently supported meeting context and attribute any residual visibility before closure. No main merge, push, shared candidate/catalog/runtime modification, acquisition, scheduler or deployment occurred.

**2026-11-06T18:43:10Z**

Completed the isolated correction for exact PDF f984b8439d21b0ef: direct bill identity is explicitly 118-H.R.4755, package edition stays unresolved, and recovered-copy fills cannot restore the rejected 4775 package. Source URLs, filename claims, saved bytes, body/link keys and supported meeting context are preserved. Reviewed commit f7988b5401937960e0ce59ad84b42f609ca43ca8 remains unchanged. All 17 focused tests passed (partial lane), including six native fixture invariant suites, independent planted-association checks and pinned cause validation. The completion audit reverified all 10 file hashes and retained the small qualification inputs durably for worktree pruning. Evidence: .cache/archive-release/implementation/reviewed-non-news-20261106/ct-yci9/{HANDOFF.md,RESULTS.json,COMPLETION-AUDIT.json,release-causes-durable.json}. A fresh independent GPT-6.1 Sol/xhigh reviewer loaded all four requested skills and returned APPROVE with high confidence for this exact commit after tracing causes, selection/fallback, retry checks, retained outputs and rollup consumers; it found no material scoped defect. Review: /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-yci9/REVIEW.md.

Keep in_progress. Root 01a1aa05 owns the consolidated source rollup and combined plan/lifetime reconciliation; ct-m104 (01a1b1b0-7f7b-7b50-8b00-6f5a05eed772) owns final native production qualification, selected release/deployment and matching MCP detail, bill-document lookup and actual site search. Any residual 4775 meeting context still needs its source basis attributed before removal or closure. Local completion is not live delivery; no further independent source work or competing build is needed.

Independent review: APPROVE for the scoped work; remaining ticket acceptance is unchanged. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-yci9/REVIEW.md).

**2026-11-08T15:26:16Z**

2026-11-08: published in archive release 63016450530114d8ebc03d2936dc8293250ffd546bf00d5205909345216e5e78 (public pointer moved; browser contract and public canary passed; hosted Explorer re-pinned in aed605d1 and read back). Causes: model/jobs/release-causes/5d24699ad9fa-630164505301.json; note: docs/releases/2026-11-08-630164505301.md. 115732 subject_keys read back without 118-hr-4775. The original array_except failed on the lake's non-null list type; fixed with array_remove_all in 3ebe6872 with a lake-typed test.
