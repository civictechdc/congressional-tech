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

**2026-10-28T04:14:12Z**

Updated consolidated-BIND keep boundary b258f488/d156a6ff: active cli_args.rs excluded. Final-current selection CTd156a6ff/DS9b59263 SHA0cdcade164547350c2da4b31bcea7feb1dd73917362e7fedfbe5cf122bf24edd:19groups714files194822populationlines,19manualranges13branchsplits. Fixed-head regeneration byte-identical/verify stale=false;7runner checks PASS0.22s. Source artifacts remain preparation only; remeasure at next qualified engine head and actual switch. No cuts.

**2026-10-28T08:01:46Z**

Refreshed preparation at CT53e4df39/DS71cc6eb: all19groups/731files/197241populationlines, SHA303de208ccfef01cbb84a5d9a6ce7d69ab57dee3612efc8a26791f6352ae198d. Fixed-head reproduction byte-identical; verify stale=false/no scanned dirty sources. Keep correction83eb8ef3→70406b41 passes9runner checks0.20s, first-flip writer/VerifiedTransfer/dataclasses/hashlib retained.19manualranges/13branchsplits remain switch gates. No source deletion; regenerate at final combined heads.

**2026-10-28T17:27:02Z**

Owner18CT scope3a/4ba contracts precede91c behavior; CODE found canonical review keeps and bad replacement paths, fixed0dc/a354 with19focusedPASS2.62s. Generator wc-l796→827 (91c body828 typo). New immutable shared/switch-inventory-4fe18d00 has18CTgroups609files128077populationlines, byte-identical fixed-head reproduction. Currentverify refuses only uncommitted4xdiagnostic test; no cleanfinalswitch claim. No DS files, cuts or live changes; old benchmark retired for active measure-archive.

**2026-10-28T20:58:15Z**

F5 preparation refreshed at committed raw9030d537:18 CT groups/609 files/128194 population lines; SHAe5c8331f851a28f964f7d8787fc9acdaae76022d617bcd2b07a07ed225ed8f82. Fixed-head regeneration byte-identical; current verify stale=false/changed source0/uncommitted scanned0/generator unchanged. Official runner19focusedPASS. Prior ONECODE findings fixed. Complete per-group paths/symbols/callers/wc-l ready; no deletion. Final combined-head remeasurement and live replacement gates remain switch-owner actions; DS deferred.

**2026-10-28T21:21:28Z**

After the reviewed D2 size fix, refreshed current source47b3b0cf:18CTgroups609files128263populationlines; SHAbc8fcb7a9975d2d9d6e3d3ab843bce14035e226a6edf28f63c66aa269b8d283e. Fixed-head regeneration remains byte-identical and --verify stale=false. Selected immutable shared/switch-inventory-bc8fcb7a. No generator behavior changes;19focused source checks already passed. Final combined-head and actual-cut remeasurements remain switch-owner gates.
