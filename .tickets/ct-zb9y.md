---
id: ct-zb9y
status: closed
deps: [ct-o24q]
links: [ct-hm4b]
created: 2026-10-18T19:26:50Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Check for publication changes before expensive setup

Every scheduled viewer check installs the full Python workspace and publication tools, prepares historical test inputs, and runs the publication fixture suite before discovering an unchanged catalog.

Source: .github/workflows/publish-filename-viewer.yml:75-99; .github/actions/setup-python-project/action.yml:13-28. The full cost is not yet timed.

## Acceptance Criteria

Separate a bounded read-only preflight from preparation. Keep code validation in CI and require current passing checks plus fresh input verification before any publication write. Measure complete no-op job duration and downloads; changed inputs or incompatible code must take the validated preparation path. Never reuse a preflight result as authority for a later write.

<!-- grade-followup:start -->
## Grade review follow-up

Workflow setup cost and refresh_recoveries read/identity duplication.

- Use correct selective release identity for early read-only decision, retain a fresh write gate, and measure complete unchanged-job work. Reusing captured identities must not weaken final separate protected-object checks; no-op still has zero table reads/writes.

[Function scope and checks: 2 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:682). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:54:42Z**

Local implementation separates stdlib bounded read-only preflight from full setup; exact release/runtime identity includes ijson; scheduled no-op skips full workspace/native-tools/fixture preparation, while code pushes still validate. All later writes retain accepted artifact inventory, original conditions and fresh protected controls. Signer is restricted to fixed GET-only keys/endpoints, UTC dates, no redirects/retries; botocore equivalence tests retained. Local absent/empty fixture: 8 private + 2 public GETs, zero table reads/writes. Complete real hosted unchanged-job duration/downloads remain PENDING future deployed observation; telemetry wiring/local fixture timing are not qualification, and no workflow was dispatched. Evidence docs/experiments/publication-remediation/evidence/control-preflight.json.

**2026-10-18T20:55:33Z**

Verified locally: expanded 147-test matrix passed; final preflight suite 44 passed including exact ijson version, all allowed key forms/signature headers matched against maintained botocore, redirect refusal, read-only allowlists and stale-input refusal. Root explicitly transferred future hosted qualification to open ct-x7vx (depends on ct-zb9y, linked ct-8uwj); full deployed no-op duration/downloads remain unmeasured and are not claimed by this implementation closure. Shared identity removes duplicate implementation and caches source hashes only under unchanged file custody; bounded comparator explicitly clears metadata warm-up cache.
