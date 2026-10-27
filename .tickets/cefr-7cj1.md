---
id: cefr-7cj1
status: closed
deps: []
links: []
created: 2026-10-27T21:02:06Z
type: task
priority: 2
assignee: raw
---
# B7: apply the owner recovery staging decisions

Resolve source category before display kind and use earliest valid same-body fetch only when exact recovered URL has no source time. Preserve excerpt decisions; restage locally with zero unresolved imports; live imports remain owner-gated.


## Notes

**2026-10-27T21:04:54Z**

Contract ac9a747c reproduced three failures/one pass. Native source selection now resolves categories before kinds and uses earliest parsed-UTC same-body fetch only when exact recovered-URL evidence has no valid time. All23 engine recovery import tests pass21.34s on engine-1c2473b. Local full restage and root independent review remain pending; no live imports.

**2026-10-27T21:08:36Z**

Full local stage7a8c74a6 retains24028decisions,12432ready imports,0unresolved in38.95s/maxRSS1166000128B. Native audit resolves exactly57category+24time gaps; sixexcerpt kinds preserved/no rejections;24earliestfetch times and source locators have0mismatches. Immutable shared/raw-recoveries-7a8c74a6 manifestSHA79feffc769a14bb7257ab2464ecc04eaeb0e308e1f29a1e482fb12058dc04c16. Final focused23pass11.86s includes a null source URL. Import inspection validates12432records without apply; actual imports and root independent review remain gates.

**2026-10-27T21:17:22Z**

CODE APPROVE and ARCH APPROVE for owner decisions ac9a747c/7a8c74a6/d560351d. Independent focused23 passed10.51s; native audit verifies all81 transitions, six excerpts/no rejections, 24 earliest fetch times and locators, immutable pins. Local restage24028 decisions/12432 ready/0unresolved. Actual body/provenance imports remain owner gated; exact commands in b7/README.md.
