---
id: cef-vai0
status: closed
deps: []
links: [ct-v967, cefr-xjsp, ct-aapl]
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

**2026-11-01T02:34:12Z**

Extended shared URL normalization per docs/plans/url-normalization.md (ct-aapl): added download-ampersand-query (House+Senate, optional fragment/space), senate-notfound (optional %2F and fragment), and lis-gpo ((?:lis|congress).gov/cgi-lis/t2GPO/) wrapper rules in model/registries/url-rules.json, plus 100% SQL-parity Python twin in corpus_recovery/url_normalization.py (0 mismatches across 74,221 corpus URLs).
