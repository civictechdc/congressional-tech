---
id: ct-l1zw
status: open
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

