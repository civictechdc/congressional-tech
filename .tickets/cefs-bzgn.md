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

**2026-10-27T20:11:05Z**

Final c1713681 full11672passed with exact36baseline identities unchanged;91merged focused pass. Engine has merged helpers/byte rule and owns publisher/maintenance consumers. Receipt-list retention/deletion consumer proof remains incomplete; keep this ticket open until integration verifies live/last-good retention and old-prefix removal.
