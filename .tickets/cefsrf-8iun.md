---
id: cefsrf-8iun
status: in_progress
deps: []
links: []
created: 2026-10-28T01:25:13Z
type: task
priority: 1
assignee: site
---
# B5 approved local Linux runtime and site publication qualification fixes

Owner retroactive review: install the approved credential-free Linux archive in CI, enroll existing reader/browser checks, and refuse pointer writes for owner-gated target receipts. E4 is paused; this isolated site-owned branch allows critical fixes to merge independently.

## Acceptance Criteria

Tests fail before B5/gate/enrollment fixes and pass after; malicious archives fail before install/export, project doctor precedes offline tests, owner-gated receipts make zero pointer PUTs, and existing CI invokes presentation/tools/saved/heap checks.

