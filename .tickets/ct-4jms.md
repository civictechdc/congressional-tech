---
id: ct-4jms
status: open
deps: []
links: [cefr-xjsp, cef-96wc, ct-tk10, ct-ud0b, ct-rie2]
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

GitHub inspection found `capture-archive.yml` (workflow 399669501) `disabled_manually`; its run query returned no runs. Repository `ARCHIVE_CAPTURE*` variables were absent. Environment and organization variables and the reason for disabling were not inspected. The workflow checks `ARCHIVE_CAPTURE_ENABLED`; passing local selection tests does not establish that scheduled capture ran.

The concrete Ashley Nunes target is `https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1`. Discovery already found that link. The base address saved an HTTP 200 HTML wrapper (`is_real_file=false`, body `ae5ee73d95a8fada1e9491574799cf263d03114d3f84d830ed26a9f6e1e0934c`); selected inputs contain no file capture/recovery, and the download target has zero attempts in e145. The first missing handoff is discovered target to file acquisition. No invocation, budget cutoff, refusal and attempted failure remain distinct possibilities until the exact queue/receipt trace is read.

Ordinary capture supports profile version 1. Explicit recovery campaigns require a separate version-2 requirements-bound input. Failure due dates follow the existing family/age retry policy; their presence alone is not a demonstrated retry defect.

## Acceptance Criteria

- Recheck workflow state, applicable variable scopes and cutover prerequisites. Enable the existing workflow and `ARCHIVE_CAPTURE_ENABLED` binding at cutover; record one successful scheduled `capture-archive.yml` invocation, run ID, source revision, exact release/profile/URL-state identity, budgets and emitted receipt keys. A manual dispatch or restored schedule alone does not meet scheduled-run acceptance.
- Verify creating receipt lines record `stored_md5` and `stored_suffix` against acknowledged stored objects. Prove receipt-referenced bodies exist and the run reads no old index. Account for each selected/cutoff target with an attempt receipt, retained result or explicit reason; preserve the observed target and repaired candidate addresses separately.
- Trace the exact Ashley base and download targets through discovery, due queue, eligibility/cutoff, attempted candidate and receipt. Run the admitted bounded attempt or record a supported refusal/exclusion; an unexplained zero-attempt target is not complete. A remote failure remains a failure with its retry/next-action disposition, not a downloaded document. If content is acquired, verify body qualification and the intended testimony relationship; hand any required alternative recovery to ct-umtm with the same locators.
- Demonstrate the existing ordinary-capture policy without weakening campaign guards. Attribute any proposed retry change to an actual repeated-request history and violated or explicitly revised policy; do not mark every failed address terminal. Keep campaign execution and publication gains out of this ticket's success claim.

## Evidence

[November 5 root-cause analysis](../docs/experiments/url-normalization-revalidation-20261105/root-causes.md); exact GitHub commands in `.cache/archive-release/investigations/url-root-cause-20261105/greybeard.md`; Ashley capture and live queries in `.cache/archive-release/investigations/url-root-cause-20261105/etl-recovery-campaign/{handoff-check.json,mcp-ashley.json}`. The retained discovery result is `docs/experiments/url-normalization-validation-20261031/evidence/discovery-link-results.json`. These are November 5 observations, not proof of future deployment state.

## Notes

**2026-11-01T20:08:14Z**

Reopened 2026-11-01: capture-archive.yml is disabled_manually with no recorded runs, and ARCHIVE_CAPTURE_ENABLED is not set. Acceptance requires a live run.
