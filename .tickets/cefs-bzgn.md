---
id: cefs-bzgn
status: closed
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

**2026-10-28 local consumer proof**

c1e78b7f adds kept_input_records and delegates the old receipt-key API to it. Every kept prefix validates its own complete evidence; shared physical objects are read once. Engine's maintenance consumer proves live/last-good/pinned retention, old unkept prefix removal, missing/corrupt kept evidence refusal and protection of every historical native selector. Latest normal merge a4a4bc5d passes 92 focused workflow/gate/receipt/maintenance checks in 2.57s, including 13 helper checks. Root's maintenance/publisher CODE review covers the shared helper and validate_receipt extraction cb340b3b; keep open until its verdict. No raw or live store addressed.

**2026-10-28T07:06:18Z**

LOCAL DONE: manager accepted precise local F4 seam closure 20261028T070251Z. Shared validate_receipt preserves existing policy/messages; kept_input_records validates every kept-prefix record/list before return, reads each physical list once and feeds the maintenance consumer. Local checks prove live/last-good/pinned and historical native selector retention, old unkept removal and missing/corrupt evidence refusal. Latest normal-merged owned group:92 focused PASS2.57s, including13 receipt helper checks. This closes phase1 local seam/consumer proof, not full-corpus acceptance, remote retention execution or live activation; spicy-regs pins remain phase2. Root F1/legacy-canary CODE review APPROVE; no broader publisher implementation certification claimed.
