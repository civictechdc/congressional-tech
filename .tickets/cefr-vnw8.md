---
id: cefr-vnw8
status: closed
deps: []
links: []
created: 2026-10-27T19:00:52Z
type: task
priority: 2
assignee: raw
---
# F5: prepare revision-pinned per-group switch deletions

Preparation only: all BIND section 6 groups with current paths, symbols, callers, wc-l, hashes, preserved consumers and owner gates. No source deletion.

## Acceptance Criteria

All 19 BIND rows plus mixed tests and rewritten docs covered; static references and uncertainty visible; unique accounting; stale-source verification; switch and phase2 gates explicit.


## Notes

**2026-10-27T19:19:21Z**

Read-only generator built under codex-raw/run2/cxb_inventory_switch.py. All 19 BIND groups covered, exact source pins/hashes/wc-l and static/dynamic caller evidence. Historical 27 mixed tests/5948 lines reproduced from d9730967. Candidate and fixed-head reproducibility measurement under run2/f5; no deletion or build. Parent raw owns independent review and final note commit.

**2026-10-27T19:24:34Z**

Final candidate switch-deletions-candidate-final.json SHA256 91e2d900d4df332abb1c1da094ea8009a0f407023e02e20d1da929ca28df4c62. Fixed CT5eba5950/DS7052dba8 regeneration byte-identical; 19 groups,629 unique files,0 unresolved path seeds,30 explicit shared/manual ranges. Historical27/5948 reproduced; currentretention28. Stale verification exit2 correctly reports subsequent committed DS changes and active uncommitted source. Own intermediates removed after measurement, retained scratch13MB. Parent review/selection and final-head remeasure remain.

**2026-10-27T19:36:41Z**

Review findings reproduced by six focused contracts on the frozen baseline generator; fixed scoped import/definition resolution, tracked src/.../target inclusion, explicit engine lifecycle integration-test paths and exact BLAKE3 fallback boundaries. Six focused production-offline contracts pass in0.13s. Canonical generator moved to scripts/measure/cxb_switch_deletions.py; scratch cxb_inventory_switch.py is only a launcher. Old candidate-final.json remains immutable; corrected candidate is generated separately.

**2026-10-27T19:40:23Z**

Confirmed reviewer concerns fixed in840977d9 after contracts e9d1e1cb/402e9f89. Corrected immutable candidate run2/f5/switch-deletions-candidate-fixed.json SHA256 b4627528edd96e2edacafa89d397b80f5c50b1b778eb3293e39d9b45fab00e7b, CT840977d9/DS4aa75aa6:19groups,683files,0unresolved paths,32explicitmanual/sharedranges. src/engine/history/target/tests.rs551linesincluded; native lifecycle integrationtests listed WAIT/MIGRATE; six focused contracts pass. Fixed-head reproduction byte-identical. Old candidate-final retained for review. Parent owns final-head regeneration, reviewed selection and README commit.

**2026-10-28T00:08:56Z**

Local F5 preparation complete at CT572ccb64/DS48636e5. Selected codex-raw/cxb_switch_deletions.json SHAa9db01c4d19c0a4e2a28abbe4ae685ae7aa1b67f22fdf4951049499f87b173c1:19groups/697unique files/193399population lines/19open manual ranges; not a deletion estimate. Historical27mixedtests/5948lines reproduced; currentretention28. Six focused runner checks pass0.09s, CODE/ARCH APPROVE preparation only. Fixed-head regeneration byte-identical; --verify stale=false with no changed/uncommitted scanned source. Shared keep boundaries/callers/phase2/live-import gates explicit. Regenerate at final combined heads and remeasure each group at switch; no source deletion or live action.

**2026-10-28T03:35:54Z**

Final reviewed-generator refresh at CT7a1f5453/DS9b59263:19groups706files194221population lines, SHA9ec321ed588350719c2ef434dff3ced242081fb31ad788e8082bde4a41c699b5. Fixed-head regeneration byte-identical; verify stale=false/no scanned dirty source;6runner checks PASS0.13s. Selected scratch cxb_switch_deletions.json refreshed, old selections retained.19manual ranges/13manual branch splits remain switch gates, not authorized deletions. Engine must regenerate at final integration heads and measure actual cuts.
