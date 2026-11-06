---
id: ct-77zb
status: open
deps: [ct-gi01, ct-t915, ct-m104, ct-5kto, cef-96wc, ct-sh4j, ct-30fp, ct-kw9b, ct-yymr, ct-vpo2, ct-aapl, ct-v51p, ct-jinw, ct-l9g0, ct-cov3, ct-vnkf, ct-h1nd, ct-wx65, ct-9wl3, ct-1l1h, ct-4jms]
links: [cef-96wc, cef-jh7i, ct-t906, ct-8kl2, ct-98sm, ct-1mbc, ct-kw9b, ct-9gmr, ct-pocg, cef-nkzp, ct-h1nd, ct-d0o0, ct-sh4j, cefr-7sar, ct-kac4, ct-3vub, cef-zrhq, ct-a3le, ct-v967, ct-082q]
created: 2026-10-30T14:32:30Z
type: epic
priority: 0
assignee: mikewolfd
tags: [phase2, engine-first, site, master-list]
---
# Complete Phase 2 with one live Explorer release

Track the switch to one native release for the site and Congress MCP. Keep the archive's retained facts and evidence accessible as the legacy publisher is retired. The original 25-item checklist and its delivered work are recorded below. The [Phase 2 annex §4.6](../docs/plans/phase-2-annex-20261028.md#46-explorer-migration-and-data-coverage) defines the remaining closure order.

**Current closure map (November 6):** [Evidence, owners and remaining actions](../docs/plans/phase-2-closure-map-20261106.md). `ct-t915` is closed for verified site implementation; `ct-m104` and `cef-96wc` retain its candidate and live checks. Candidate `720c495b66d1` is completed but private and predates newer MCP changes. The final non-indexed release remains with the MCP coordinator. Preserve the original checklist and notes below.

## Acceptance Criteria

- Record `ct-gi01`'s retained-field inventory, dispositions and actual native production inputs, then `ct-t915` and `ct-m104` acceptance on the same selected release. The selected HTML metadata stays under `ct-082q`.
- Record `cef-96wc`'s live switch, workflow bindings and rollback evidence, then `ct-5kto`'s retirement of the separate writer, pointer and staging.
- Account for applicable linked work in the original seven tracks and the remaining runtime, raw-safety, schema and operations checks under their owners, including lock readback on `ct-1l1h` and scheduled capture on `ct-4jms`. The parked News Lake and standalone classifier and diagnostic cleanup have separate owners. Keep local qualification, integrated work and live acceptance separate. Reuse completed evidence when the inputs, code and release still match.

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

**2026-10-30T21:20:20Z**

Accepted blind-review follow-through: new ct-sh4j owns GB1; new ct-30fp owns the related GB2/GB4/GB5 observation semantics; reopened ct-yymr and ct-kw9b own GB3 handoff/admission, coordinated with existing ct-vpo2 and ct-h1nd. Model, annex, implementation plan, bindings, switch checklist and fixture manifest now specify the corrected target. All implementation/qualification remains open.

**2026-11-01T10:39:01Z**

Independent 13-Ticket Validation Swarm Reconciliation (2026-11-01):
- Executed independent subagent validation across all 13 recently closed tickets (`ct-aapl`, `ct-v51p`, `ct-jinw`, `ct-l9g0`, `ct-cov3`, `ct-vnkf`, `ct-h1nd`, `ct-30fp`, `ct-vpo2`, `ct-yymr`, `ct-kw9b`, `ct-wx65`, `ct-sh4j`) plus cross-cutting binding, byte-hashed parser, and 5-suite regression checks (`9,734` tests).
- Reopened all 13 tickets with exact per-ticket audit notes to track their 5 Priority 1 functional/operational defects (`ct-30fp`, `ct-vnkf`, `ct-kw9b`, `ct-sh4j`), 8 Priority 2 edge-case/tightening items (`ct-30fp`, `ct-h1nd`, `ct-wx65`, `ct-yymr`, `ct-vpo2`, `ct-l9g0`, `ct-jinw`, `ct-cov3`, `ct-aapl`, `ct-v51p`), uncommitted working-tree state, and downstream publication/reconciliation steps.
- Created `ct-9wl3` to track the 3 pre-existing commit `12ac8bf2` test regressions uncovered by the 5-suite cross-cutting run (`test_review_provenance.py`, `test_capture_review_contract.py`, `test_congress_api_imports.py`).

**2026-11-01T20:08:15Z**

Reconciliation 2026-11-01: the 13 tickets reopened at 10:39Z were re-closed at 12:05Z. New or changed: ct-itcg (Basin), ct-9gmr (checked-in selective backfill), ct-qg8e (row counts), ct-2c0w (CI runtime), ct-deh9 (version selection), ct-nkw9 (stale docs), ct-p3ff (SQL rule). ct-kac4 rejected. ct-4jms and ct-klyz reopened.

**2026-11-01T20:47:10Z**

Owner decision 2026-11-01: B10 and B13 no longer gate the exit (annex §4.1). ct-gi01 stays native with the weekly job removed, ct-m104 keeps its ct-0a37 dependency, and cef-96wc keeps ct-9gmr.

**2026-11-02T01:18:04Z**

Owner decisions 2026-11-01: batch all parser fixes into one version move (uv pin for extruct, House times and rooms ct-cjwx, HTTP 202 ct-c6b0, body_complete ct-v8y0, daily D4 ct-kn6d, Senate pages ct-egg6), and use a compatible-version rule (ct-deh9, moved into Round 1) rather than re-stamping every row. Merge order: Basin commit of v21 inputs by the owner first, then clusters, with pins recomputed once at integration, then one backfill and one model run.

**2026-11-02T04:01:45Z**

Round 1 stopped at owner direction 2026-11-01 after reviewing and fixing. Unmerged: worktree-agent-ae42a8cf7a429ba24 @ 180a49b1; worktree-agent-a704015cc138b456b @ da425206; worktree-agent-a5550c04138214670 @ b3c4aa3c. Worktrees retained. Next steps, not started: owner Basin commit, integration with one pin recompute, wiring ct-deh9, captures rebuild, backfill, one full model run, key comparison, publish.

**2026-11-02T12:28:28Z**

Round 1b 2026-11-02 (lead): Integration of clusters B/C/D: 63 lane failures, none a production defect (fixtures and checks out of step). Process cause confirmed: cluster C's worktree had no .venv, so its tests ran main's package code. Briefs now require uv sync --frozen per worktree. New model_sql relation check being rebuilt on the existing sql_dependencies after red/green review.

**2026-11-02T13:13:02Z**

2026-11-02 (lead): integrate-round1 green at 98fb1424 (production-offline 10,795 passed, peak 3.5 GiB) after red/green review fixes: shared SQL dependencies use the existing DuckDB parser (moved into congress_api/lake/model_sql.py), step-order test, and publish refuses converted catalogs. Pushed as a branch only. Code does not go to main before publish, because a main push deploys Pages (apps/site, uv.lock) and the old Explorer publisher (congress_api) against the old live release. The new site and release ship together.

**2026-11-02T13:54:36Z**

2026-11-02 (lead): trial merge of all 7 branches onto integrate-round1: 9 conflicts, all resolved by keeping both sides; lane 10,978 passed, 11 failed, 5 errors, all cross-branch (f x g fixture inputs, e2 x g proof basis, h x g SQL anchor, h x e1 duplicate mapping_version fixture and the 202 mutant, 2 xfails now passing, step count 180). Recipe: .cache/rounds/r1b/trial-merge.md. Drop e2's own pin commit e73505b2; recompute pins once.

**2026-11-02T16:28:57Z**

2026-11-02 (lead): etl-rca correction: cluster C's integration failures were NOT from running main's code. C's tests ran the branch's code but only --path subsets, which hid the failures. Fix 9631f1be on r4-rca: pytest and doctor refuse another checkout's interpreter or imports, and every run prints whether it was a partial or full lane. e13a3382 binds the engine to the branch pin through a content-addressed store (.cache/docspec-runtime); before it, verify_runtime didn't enforce the pin, so several branches pinning eb40c54 tested on 5dae611.

**2026-11-02T17:17:02Z**

Owner decision 2026-11-02: runner fixes (r4-rca: refuse another checkout's code or a mismatched engine pin; partial/full lane line) ship with this release after a light check.

**2026-11-02T17:41:18Z**

2026-11-02 etl-rca done (RCA: .cache/archive-release/investigations/rca/RCA.md). Ships with the release after a light check (owner decision): r4-rca~1 = 0ece1bb8, rebased as r4-rca-rel onto 44785aee. Item 3: tests refuse another checkout's interpreter or imports and print the run scope (4b74befd, d8d5149b); C's failures hid behind --path subsets, not main's code. Item 4: doctor binds to the branch pin, and binaries are installed read-only and content-addressed (9beffd76). Item 6: the watchdog admits on measured free memory and stops the youngest at the floor (1a0bb6d9, 0ece1bb8). Item 7: dev.py prune-worktree refuses on ignored data or a running process (908059de). Item 5: docspec-rs CI runs this repo's whole lane in 6 shards (797083f, 0d65b47, 5a7fa9f on docspec-rs main; the probe on 425e346 failed first with the ss-x71z error), plus a raw-check rule and lint (f5fa384c). Held: item 1 (1f6effdf: parser versions hash only the locked packages they import) and item 2, unfixed (compatible_proof.py and 2-17 imported workspace modules are hashed by nothing); timing goes to the owner. Follow-up: production jobs still trust the config's own binary claim; flip after the release. Brief now requires a (full lane) line at hand-off.

**2026-11-02T17:45:21Z**

2026-11-02 green-rca (light check of r4-rca~1): MERGE WITH FIXES; nothing blocks the release path or production. Fixes sent to etl-rca: prune-worktree treats build/dist/target as disposable at any depth (scripts/dev.py:309-315, a data-loss path), and the watchdog's floor victim can be a dead job with a reused PID (archive_watchdog.py:95,101,208).

**2026-11-02T18:21:40Z**

2026-11-02 r4-rca-rel 77ebb23f (both green-rca fixes in: prune-worktree treats build/dist/target/.astro as disposable only at packages/<name>/ or apps/<name>/; watchdog entries match on PID plus start time; lint searches subdirectories): full lane 11,064 passed, only the two expected pin tests failing; 'production-offline (full lane): exit 1', peak 3.62 GiB, 28:35. On release-train.

**2026-11-02T18:29:11Z**

2026-11-02 lead RCA: train's first full lane on release-train exited 143 at 49% (13:27:10), killed by impl-f's `pkill -f "scripts/dev.py test production-offline$"`, which matches every agent's full lane. spec-run and impl-model also stop jobs with pattern kills (pkill -f on run_release.py, chain.sh, 'guard.py --rss-gb 16 .*archive_backfill_job'). Cause: on a shared machine where agents run identical commands, a pattern is not an identity. Rule added to the agent brief: stop only the PID you started (signalling the guard takes down its child group). Follow-up: have the guard print its PID at start, so agents can record it.

**2026-11-02T20:55:01Z**

2026-11-02 release-train 8244904f full lane: 'production-offline (full lane): exit 0', 11,244 passed, 37 skipped, 3 xfailed, peak 1.92 GiB, on engine b0342a7's config; archive_schema --check passes. 82e5b35d adds ci-poppler c006c4fa (CI and setup only; 43 own tests pass; doctor passes). Pins moved vs candidate-r1b: D4 record pins (meeting congress_gov and house_xml, four appearance pins, committee house_xml), readings bundle a7a8c404, model_spec 551c0820 (size 3115); captures, the four reading pins, catalog and video unchanged. Open: release key invariant (54 rows, inv-rca); the DOCSPEC_RUNTIME_ARTIFACT switch at the main merge.

**2026-11-03T22:53:52Z**

Progress update 2026-11-03: Release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd is LIVE at https://congressional-data.spicygov.ai/viewer-publications/manifest.json (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419). All 5 publish gates passed (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), 7 gated lake snapshots exported and imported to Basin with producer proofs, full production-offline lane passed (10,967 passed on release-train), contract:archive and live canary:archive passed, and congressional-explorer-mcp (v0.5.1, 22 tables) verified live against the published pointer.

**2026-11-05T17:11:15Z**

2026-11-05 ticket consolidation: remain the single Phase 2 coordination index. Superseded trackers ct-7uit, ct-mi03, ct-a1aa, ct-8kl2, ct-98sm and ct-v967 retain history and named successors. Active congressional producer/site/MCP/live-switch/retirement remain ct-gi01, ct-t915, ct-m104, cef-96wc and ct-5kto; raw lock/capture checks remain ct-1l1h and ct-4jms. Keep ct-082q as the scoped HTML milestone. Parked ct-d8cf/news and standalone classifier/diagnostic cleanup do not become new Phase 2 gates. Public roster wording and archive keyed-document delivery are recorded on ct-mx3g/ct-mt0h, with installation readback under ct-m104 and actual SpicyEngine adoption under ss-7ih1. Closed superseded records never prove their successors' acceptance.

**2026-11-05T20:08:15Z**

November 5 URL root-cause ticket reconciliation: updated ct-umtm (twelve replay custody/acceptance/import/publication dispositions), ct-4jms (ordinary scheduled capture plus Ashley queue/receipt trace), and ct-nh41 (producer explanation repair). New owners are [ct-yci9](ct-yci9.md) for agreeing wrong filenames, [ct-5esu](ct-5esu.md) for supported lookup aliases, and [ct-rie2](ct-rie2.md) for a requirements-bound campaign with final target/body/publication metrics. The first two are children of ct-gi01; the campaign is a child here. Links express shared evidence, not artificial execution dependencies: ordinary capture and explicit campaigns can be qualified separately. Existing completed normalization and filename-conflict tickets stay closed. [Root-cause report](../docs/experiments/url-normalization-revalidation-20261105/root-causes.md). No production changes, new acquisition, workflow enablement or publication accompanied this ticket update.

**2026-11-05T23:55:26Z**

Closed 13 completed implementation tickets at the user’s request: Wave 1 ct-t915, ct-j78x, ct-j49p, ct-67k1, ct-dx22, ct-lx67, ct-opy0, ct-j9o7, ct-cxc5 and ct-717p; Wave 2 ct-k2ij, ct-db3w and ct-ud0b. Independent Sol/xhigh greybeard/ETL reviewers checked the retained evidence and current scope.

ct-gi01 retains combined native/candidate obligations; ct-m104 retains same-release reader acceptance; cef-96wc retains live cutover and the Mac scheduled publication check. Source gaps, legacy accounting, historical rosters, the unmerged upstream comparator and old-writer retirement remain open with their existing owners. Concurrent additions to ct-9s7b and ct-m94a introduce unfinished implementation, so those tickets stay open while crediting their completed original fixes. No new release or deployment is claimed.

**2026-11-06T16:37:39Z**

November 6 closure-map reconciliation at source 742dbe70: docs/plans/phase-2-closure-map-20261106.md records the four active handoffs, original seven-track accounting and explicit raw/source/operations gaps. ct-t915 remains closed for verified implementation; its candidate and live obligations stay with ct-m104/cef-96wc. The completed private 720c495b66d1 candidate and 69 unaccepted comparison groups are credited separately from the final non-indexed release. Existing release/MCP coordinators retain cause review and final release execution; ct-5kto retains retirement after live acceptance.

Added direct dependencies on ct-1l1h and ct-4jms to reflect this milestone's existing raw-lock and scheduled-capture acceptance. Original dependencies, checklist, notes and completed implementation history remain intact. Corpus indexing, News and standalone cleanup stay outside the active release's exit checks. No source/runtime change, new model, publication, deployment, schedule change or ticket closure accompanies this documentation-only reconciliation.

**2026-11-06T18:43:10Z**

Completed the Phase 2 closure map and milestone reconciliation in f1d8ab05, preserving the original seven-track checklist, acceptance and full history. The map credits accepted site implementation and retained candidate work and names the remaining producer, reader, live-switch and retirement owners. Verification passed for 27 links/anchors, unchanged history/acceptance, exact dependencies and five retained candidate file pins; no new model or application tests were needed. The completion recheck credits the newer ct-gi01 inventory, ct-x78c ledger, cef-96wc live readback and prepared ct-5kto retirement patch. The original commit is now included in the source rollup; it is not yet in main at this check. All independent umbrella work is complete; current evidence and handoff are under .cache/archive-release/implementation/reviewed-non-news-20261106/ct-77zb/. Independent GPT-6.1 Sol/xhigh review, after loading all four requested skills, approved this exact commit and the current note with no blocking findings; it confirmed the coordination issue is addressed without claiming Phase 2 or live acceptance.

Remain open. Original root 01a1aa05 owns the source/main rollup; ct-m104 (01a1b1b0) owns the final native build, deployment and same-release consumer acceptance. ct-gi01/ct-x78c retain preservation/source dispositions; ct-082q has qualified its daily-source work and is source-freeze-ready (192,959 selected pairs, zero pending; unchanged-daily and changed-head controls passed); source-rollup integration and final candidate/reader acceptance remain; cef-96wc retains live switch, rollback and unattended Mac publication; ct-5kto retains retirement after live acceptance; ct-1l1h/ct-4jms retain effective raw-lock and actual scheduled-capture evidence. Local preparation does not establish live delivery.

Independent review: APPROVE for the scoped work; remaining ticket acceptance is unchanged. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-77zb/REVIEW.md).
