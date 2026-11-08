---
id: ct-l1zw
status: closed
deps: []
links: []
created: 2026-11-08T18:00:21Z
type: bug
priority: 3
assignee: mikewolfd
tags: [site, ci, flaky]
---
# Fix the route.fulfill race in the archive browser test helper

validate-explorer run 42505474370 (attempt 1) failed test_recovery_publication_journey.py::test_retained_import_publish_resume_selected_reader_and_real_queue in the native-loopback step: the contract:archive script threw 'route.fulfill: Fetch response has been disposed' at apps/site/scripts/archive-browser.mjs:20. Attempt 2 passed with no code change, and neither file changed since 2026-11-07, so this is a race. The route handler probably fulfills after the page or response is torn down. Await or guard the fulfill (catch the disposed-response error only for already-closed pages) and add a stress run.


## Notes

**2026-11-08T18:59:30Z**

Fix on branch claude/ct-l1zw-m7sy: routeWhileOpen (apps/site/scripts/archive-browser.mjs) wraps archive-origin and contract body-route handlers; a fetch/fulfill rejection is ignored only when the owning page/context has closed, otherwise rethrown. Stress: verify-archive-contract.py 15/15 passes locally, no 'disposed' errors. Journey test not rerun locally (native-loopback needs SOURCE_FETCH_BINARY).

**2026-11-08T20:01:35Z**

2026-11-08 closed: routeWhileOpen guards fetch/fulfill after page or context teardown and rethrows on open pages (c0319370, merged with 5c7de195). 15/15 consecutive archive-contract runs passed; validate-explorer green on the branch (run 42516117742). The original flake was seen once in CI and never reproduced locally.
