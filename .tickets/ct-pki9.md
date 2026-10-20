---
id: ct-pki9
status: closed
deps: []
links: []
created: 2026-10-20T16:03:45Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-czsd
---
# Keep viewer publication linked to the renamed capture workflow

The capture workflow was renamed to update document tables, but the viewer workflow_run trigger still uses the old rebuild name. Successful captures would no longer trigger publication immediately.

## Acceptance Criteria

Match the upstream workflow name and add a regression comparing the maintained workflow names. Preserve existing success, repository and event guards; no workflow dispatch.


## Notes

**2026-10-20T16:05:05Z**

Fixed downstream workflow_run to match the maintained capture workflow name. Regression failed on the old name, then all 43 workflow tests passed in 2.34 s. Independently confirmed by migration acceptance reviewer; existing success/repository/push guards remain unchanged. Evidence: review-merge/workflow-name-red.xml and workflow-name-green.xml. Grade A for this bounded correction; no workflows dispatched.
