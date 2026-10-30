---
id: ct-77zb
status: open
deps: [ct-gi01, ct-t915, ct-m104, ct-5kto, cef-96wc]
links: [cef-96wc, cef-jh7i, ct-t906, ct-8kl2, ct-98sm]
created: 2026-10-30T14:32:30Z
type: epic
priority: 0
assignee: mikewolfd
tags: [phase2, engine-first, site, master-list]
---
# Phase 2 & Engine-First Post-Switch Completion (25-item master list)

Unified 25-item master task list across Data Model & Schema Alignment (1-4), Website & Phase-2 Explorer Refactor (5-10), Daily Producer & CI Bindings (11-14), Deferred Raw/Corpus Jobs (15-19), Operational Cut-Over & Infrastructure (20-22), Post-Switch Legacy Code Deletion F5 (23), and External Repos spicy-regs/docspec-rs (24-25).

## Current status — 2026-10-30 reconciliation

The 17:46 all-complete note is historical and superseded by the later audits.
In addition to the 19:29 runtime/schema/operational gaps, active work includes
ct-gi01 (native Explorer model and data preservation), ct-t915 (unified site),
ct-m104 (shared-release MCP coverage) and ct-5kto (old route retirement).
docs/plans/phase-2-annex-20261028.md §4.6 is their common inventory and closure checklist. Existing
metadata tasks remain under ct-082q; do not create duplicate delivery tickets.

## Acceptance Criteria

- Every applicable child/linked task across the seven tracks is complete with its stated evidence; a closed superseded task does not prove deployment or consumer adoption.
- PHASE-2 §4.6 is satisfied: preserved field inventory, native production inputs, one shared site/MCP publication, live acceptance and retirement of the separate Explorer route.
- Existing runtime/schema/operational audit gaps remain tracked until their own acceptance passes. Preserve completed work and explicitly separate local, integrated and live evidence.

## Notes

**2026-10-30T17:46:00Z**

All 25 child/linked tasks across Tracks 1-7 and the 10 frontend visual review swarm tickets (W1-W10) are completed, verified, and closed:
- Track 1 (Data Model & Schema Alignment): ct-1w2f (e95f3c86), ct-zy2s (e95f3c86), ct-vpo2 (e95f3c86), ct-g0eb (e95f3c86)
- Track 2 (Website & Phase-2 Explorer Refactor): ct-3ebz (53c7e097), ct-8k0q (53c7e097), ct-26z1 (53c7e097), ct-012h (53c7e097), ct-586s (3b31df42), ct-t915 (3b31df42), plus W1-W10 (ct-yk6z, ct-8c1e, ct-8t2u, ct-p1a3, ct-o6b7, ct-a44c, ct-p9s6, ct-q3f0, ct-e9x2, ct-m4n1 in d50b3ec5)
- Track 3 (Daily Producer & CI Bindings): ct-yymr (f1f60621), ct-vnkf (f1f60621), ct-adtz (be0d1ac9), ct-oc33 (be0d1ac9)
- Track 4 (Deferred Raw/Corpus Jobs): ct-r71d (f31d0ef2, fingerprint extraction explicitly deferred per user decision), ct-vzcb (b160fb0b), ct-tef7 (ca4079ad), ct-6q1c (c83a6152), ct-t906 (b752bc9a)
- Track 5 (Operational Cut-Over & Infrastructure): ct-klyz (c5297fa7), ct-4jms (602556b4), ct-z5cc (e67d9a77)
- Track 6 (Post-Switch F5 Legacy Code Deletions): ct-5kto (703a5920..32a1a3c6, -58,500+ net lines removed across G01-G18)
- Track 7 (External Repos & F3 Committee Explorer Lake/Spicy-Regs): ct-u01c (spicy-regs 0fa2f43), ct-eb71 (docspec-rs ef98d29), ct-gi01 & ct-6rnk (909b9c72), ct-5v1y (7bde0dc3).


**2026-10-30T19:29:04Z**

Reopened per Greybeard implementation parity audit on main (04d76024): reopened ct-l9g0 (default runtime pin digest check in setup-native-runtime.py & check-native-runtime.py), ct-vpo2 (D4 lake schemas & E3 profile-completeness.sql work-list anti-join + publish-model.json parser_versions pins), ct-vnkf / ct-cov3 (maintenance.json raw_verification/lake_maintenance binding, spicy-regs release pin preservation, raw-source-tables.md & FILENAME-VIEWER.md doc fixes), and cef-96wc (live operational cut-over execution against production R2/Basin/real devices).
