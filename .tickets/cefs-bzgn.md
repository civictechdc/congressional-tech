---
id: cefs-bzgn
status: in_progress
deps: []
links: []
created: 2026-10-27T17:10:10Z
type: task
priority: 2
assignee: site
---
# F4 phase1 receipt-key lists through publish and maintenance

Run2 owner reassignment. Phase1 only; spicy-regs pins phase2. Reuse engine movement and publisher conditional writes.

## Acceptance Criteria

Sorted content-addressed receipt lists verified and preserved for kept inputs; local maintenance test retains live/last-good and removes only old unkept release lists


## Notes

**2026-10-27T18:57:48Z**

Receipt helpers implemented a4237c67, agreedshape foldedDM8.1f1de2acf. Canonical sorted receipt lists and all producing input identities remain perrelease; corruption/missing evidence refuses kept-list validation. Engine confirmed it will adopt helpers in publisher and owns actual maintenance retention; consumer proof of live/last-good retention and old-prefix deletion remains open until that integration. Focused helper/gate17 and full11612/same36 pass; no storage writes.
