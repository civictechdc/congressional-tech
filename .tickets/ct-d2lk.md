---
id: ct-d2lk
status: closed
deps: []
links: []
created: 2026-10-18T19:25:05Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Verify pinned review bytes before generating identities

The identity CLI describes its input as verified but reads arbitrary review JSON. Catalog/member checks and bind-back do not verify those bytes against the checked-in review descriptor.

Source: apps/site/scripts/filename_review_binding.py:72-88. The live browser checks review pins separately; this finding concerns the offline CLI.

## Acceptance Criteria

Require and verify the pinned review descriptor or an equivalent verified input before writing identities. Reject modified review bytes, wrong pins and catalog/member mismatches. Preserve the existing bind-back checks and valid current output.

<!-- grade-followup:start -->
## Grade review follow-up

Alongside pinned review input verification, validate loaded stable-identity structure, pins, duplicate row identifiers, and required versus deliberately optional absence.

- Reject malformed identity schemas/duplicate indexes or documents and wrong/missing required pins before generating or binding output.
- Retain intentional disablement, valid current identity bytes, exact catalog/member checks and unchanged withdrawal reasons.

[Function scope and checks: 3 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:292). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:10:35Z**

Offline CLI now verifies descriptor-bound exact review bytes before catalog loading/output. Loaded identities validate required pins, rows and unique indexes/documents/source members; required missing files fail and explicit None still disables builder binding. Existing withdrawal/bind-back tests retained; 29 focused tests passed.
