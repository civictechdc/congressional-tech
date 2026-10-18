---
id: ct-l3s4
status: closed
deps: []
links: [ct-hfrv]
created: 2026-10-18T19:25:28Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Restart publication watching after back navigation

pagehide stops the publication watcher once, but no pageshow handler restarts it. A page restored from the browser back-forward cache can therefore keep showing its old selection without update notices.

Source: apps/site/src/components/filename-bootstrap.mjs:13-20. This lifecycle gap was found statically; it has not been reproduced in a live browser.

## Acceptance Criteria

Model watcher start/stop explicitly. Test a persisted pagehide/pageshow cycle: exactly one watcher restarts and notices a new selection; permanent unload stops it. Avoid duplicate timers/listeners and preserve pinned-snapshot behavior.

<!-- grade-followup:start -->
## Grade review follow-up

Include in-flight freshness-poll cancellation, pending-info history navigation and cleanup/restoration under persisted pagehide/pageshow.

- Exactly one watcher is active after restoration and none after final disposal; stopped polls do not notify.
- Popstate before info waits or is reconciled to the latest URL without throwing; pinned catalog is preserved.

[Function scope and checks: 5 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:469). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:12:01Z**

Implemented and verified in browser batch 1. See docs/experiments/publication-remediation/browser.md. Focused Node suites cover lifecycle, rules, review policy, actual worker routes and recovery fail-closed checks; existing UI suite remains green.
