---
id: ct-l7uh
status: open
deps: []
links: [ct-umtm]
created: 2026-11-08T18:59:37Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
---
# Refetch the twelve Oct 31 Wayback bodies not in raw

The twelve October 31 Wayback replay target/body pairs (ct-umtm) are recorded as not in raw: ledger .cache/archive-release/implementation/ct-umtm-20261108/wayback-not-in-raw.json. If wanted, refetch each exact Wayback body once through the maintained capture/recovery path (capture_schedule + retained import, as ct-rie2 did for USAID), verify its body hash against the ledger, and import only on qualified identity. Out of scope: proving semantic equivalence; one CHRG-110hhrg41994 counterpart is a possible but unproved match.


## Notes

**2026-11-09T17:57:05Z**

2026-11-09 owner decision: build the recovery route. Scope: add exact Internet Archive replay as a recovery source kind (exact-replay scope entry with expected body hash), recovery requirements for the twelve ct-umtm targets in publish-model.json, capture_schedule --campaign support in the workflow, and one supervised import verified against the ledger. Follow the ct-rie2 USAID campaign as the template. Scheduled after thread 1 (claude/ct-thread1-unattended) lands.
