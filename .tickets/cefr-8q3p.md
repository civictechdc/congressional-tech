---
id: cefr-8q3p
status: closed
deps: []
links: []
created: 2026-10-27T14:03:56Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B7: reconcile recovery decisions and import through raw components

## Acceptance Criteria

Native reconciliation preserves accepted and receipt-only recoveries, six excerpt decisions listed, staged provenance and missing-import requests, thin imports through ReceiptWriter and BodyStore, focused tests pass; owner imports remain gated.


## Notes

**2026-10-27T14:13:43Z**

Contract extension 70646c1d measured wc-l is 95 before/125 after (body incorrectly said129); no assertions removed. Native normalized reconciliation and thin import focus passed before added refusal cases; final suite pending.

**2026-10-27T14:51:32Z**

B7 implementation 0a55702e and retained-reference binding e8a0de13; architecture category concern fixed after contract3701c6f7 in87bc28fd. Focused combined82pass; full local803.55s/6.25GB maxRSS correctly refused on7rows/5unregistered categories, no provenance published. Exact ownercommands and6excerpt decisions in docs/measurements/engine-first-20261027/b7/. Pending engine registry and independent code/architecture review; no live imports.

**2026-10-27T15:38:48Z**

Local done: canonical E1 stage contains all24,028 decisions; source facts reused without raw/PDF rereads. Current readiness92;12,316 need canonical import-category choice and24 need exact source-time qualification (41 existing body receipt candidates). Six actual excerpt claims listed. Code schema and architecture category concerns fixed,92 focused checks pass. Owner/E1/E4/live imports remain gated with exact commands.

**2026-10-27T15:43:39Z**

Architect clarification implemented after contract f8639b14: native unique category==kind==display_kind join admits an identity category only after actual/explicit choices; explicit invalid category still refuses. Focused B7/provenance/import-fence88passed in4.95s (cxb_identity_category_fix.log). Existing owner import/parity gates unchanged; no heavy corpus or live jobs executed.

**2026-10-27T15:52:57Z**

Final canonical explicit-policy stage:24,028 decisions;12,351 ready imports and81 unresolved (57 category conflicts,24 exact URL/source-time associations). All24 time cases have41 existing body-receipt candidates. Source binding4bcaa112 uses the single E1 import_category route; canonical18-row policy4d8e94dc merged. Immutable selected stage raw-recoveries-4bcaa112; older92-ready stage is not selected. Final explicit-policy88 checks and schema92 checks pass; no live import.
