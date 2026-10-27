---
id: cef-vai0
status: closed
deps: []
links: []
created: 2026-10-27T19:44:24Z
type: task
priority: 1
assignee: mikewolfd
---
# Share native URL join-key normalization across model and scheduler

E1/E2 URL rule slice: one model SQL rule with pinned wrapper/strip registry and active variant validation, reused by F2. Done when native vectors and code/architecture reviews pass.


## Notes

**2026-10-27T20:10:30Z**

Closed shared URL slice:7native groups pass. CODE3/ARCH2 concerns confirmed and fixed e61c5ab7 with fixturesdd4fe04f/8ad67850. Two-step retained normalization, literal URLs preserved, normalized variants once, separate still_wrapped reporting. Whole E1 registry seed coverage remains open.
