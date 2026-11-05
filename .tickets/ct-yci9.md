---
id: ct-yci9
status: open
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

`source-annotations-final.sql` correctly records the source filename claims. `document-packages.sql` only catches disagreements among filename-derived bill candidates, so two agreeing wrong names pass. `document-metadata.sql` independently unions filename-derived `measure_keys`, leaving a second wrong association even if package selection is cleared. The recovery bill checker is not on the original-capture path. The current policy lacks a document-level decision for contradictory body evidence; this is not a filename parsing or reader formatting error.

[November 5 root-cause analysis](../docs/experiments/url-normalization-revalidation-20261105/root-causes.md). Exact PDF and probe evidence: `.cache/archive-release/investigations/url-root-cause-20261105/etl-identity-lookup/{REPORT.md,probe-results.json,live-mcp.json}`. Source inspected at c3ee2eec; release e145d24c389e. ct-flg9's closed disagreeing-filenames repair and ct-j9o7's missing-type recovery address different cases.

## Design

Owner: document package and direct measure selection. Choose the smallest maintained, evidence-bound decision path for the demonstrated body/component. Existing review verdicts do not support package/measure overrides, so do not describe this as an existing configuration toggle. Preserve literal source claims and public body identity. Reuse retained captures and filename readings; limit semantic recomputation to affected components and downstream metadata. Shared export costs must be measured separately.

Do not apply the recovery helper wholesale to ordinary originals: first-page references to multiple bills and unnumbered drafts can be flagged, while the helper alone does not establish Congress or package version. Do not hide the entire document or hard-code a replacement package in the reader.

## Acceptance Criteria

- Retain a body-bound adjudication with the actual cover/text and source locators. The exact demonstrated document no longer asserts unsupported `BILLS-118hr4775ih` or direct measure `118-hr-4775`; both package and measure paths are checked.
- Preserve its bytes, both source URLs, captured filename, source annotation claims, body/link keys and availability. Assert a 118-H.R.4755 relationship only with an explicit supported decision; keep package identity unresolved unless the exact package version is independently established. Do not infer `4755ih` from the bill number.
- Use bounded controls for agreeing wrong filenames, disagreeing filenames, stronger authoritative package evidence, same-bill editions, an unnumbered draft, a page mentioning another bill and a different Congress with the same number. A body mention alone must not override an unrelated document's identity. Independent evidence must detect a planted wrong association.
- Verify the owning model outputs and maintained release checks, including source preservation and cause attribution. Through the selected public release, MCP document detail, bill-entity document lookup and actual site search agree on the corrected associations; recovery unit tests alone do not meet acceptance.
- Record the exact affected subset and unsupported/unresolved cases. Start with this one body/two-source counterexample and already-adjudicated contradictions; no global PDF scan or parser-version change is required merely to fix it.
