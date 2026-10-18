---
id: ct-1mbc
status: closed
deps: []
links: [ct-atjy, ct-ylaw, ct-fcxg, ct-pd8n]
created: 2026-10-18T19:44:01Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Make publication resume and failure status inspectable

Workflow resume needs five manual fields, verify_github_artifact groups custody mismatches, and CLI exceptions can leave the prior prepared report as the only summary. Emit one discoverable original-attempt descriptor, command-specific validation, clear custody diagnostics and a final outcome receipt. Sources: publish-filename-viewer.yml:75-157, publish-viewer-r2.py:470-516, viewer_publication_attempt.py:138-150.

## Acceptance Criteria

A read-only lookup produces the original revision/run/artifact ID/digest/attempt descriptor; explicit resume consumes or verifies it without granting automatic retry. Invalid combinations and custody fields fail before mutation with exact credential-free explanations. All failure paths preserve the original exception and record failed/superseded/completed status rather than stale prepared success; reconciliation progress is bounded and never asserts verification early. Retain original artifact/runtime binding and artifact-before-write ordering.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 5 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:209). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:28:12Z**

Added describe-attempt read-only lookup, exact original revision/run/artifact ID/digest/name/attempt descriptor and explicit --resume-descriptor consumption with original checkout check. Command-specific invalid combos fail before SDK construction; custody errors identify exact mismatched field. CLI exceptions atomically replace report with failed command outcome, preserve original exception if diagnostic save fails.40attempt/CLI tests plus15focused custody/descriptor cases passed; original artifact-before-write and runner-loss matrix retained.

**2026-10-18T20:33:12Z**

Independent review corrections: argparse now runs inside failure reporting with only explicitly supplied report/directory safely recovered for invalid command/flag/missing-value errors; SystemExit2 survives while stale prepared report becomes failed. Artifact verification/discovery require expired is exactly False, so missing/null/string/zero never count as known unexpired.21focused tests passed including parse failures and malformed expiry.
