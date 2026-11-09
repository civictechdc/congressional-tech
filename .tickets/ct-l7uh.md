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

**2026-11-09T17:57:46Z**

2026-11-09 correction: no new source kind is needed. The URL model already unwraps web.archive.org/web/<ts>/<url> wrappers (engine-first-data-model.md, unwrap(url)), and the ct-rie2 recovery-campaign route (recovery_requirements parquet under recovery-identity-v1, capture_schedule --campaign, supervised import) is the existing path for exactly this. Scope is therefore: one requirements file listing the twelve ct-umtm targets with the ledger's expected body hashes, one campaign run, one supervised import; verify each body hash against .cache/archive-release/implementation/ct-umtm-20261108/wayback-not-in-raw.json. The only reason scheduled capture cannot take them is that it plans from the release scope, which has no replay family; campaigns do not use that scope.
