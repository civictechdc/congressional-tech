---
id: ct-gi01
status: open
deps: [ct-sh4j, ct-30fp, ct-kw9b, ct-wx65, ct-h1nd, ct-v51p]
links: [ct-8kl2, ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-aia9, ct-2yl5, ct-bwac, ct-a3le, ct-0odd, ct-ec91, ct-3ttc, ct-84xa, ct-h23e, ct-f7p8, ct-98sm, ct-r6xw, ct-jnw5, ct-4g55, ct-xx7q, ct-s9p2, ct-w8dc, ct-93zs, ct-m104, ct-t915, ct-5kto, ct-m94a, ct-64el, ct-asdg, ct-n61r, ct-66ns, ct-n6fz, ct-o2pr, ct-1i4q, ct-9s7b, ct-7uit, ct-082q, ct-6r1i, ct-oh9y]
created: 2026-10-21T20:53:31Z
type: feature
priority: 1
assignee: mikewolfd
external-ref: ss-023x,ss-65bz,ss-6gwu
parent: ct-77zb
tags: [committee_explorer, congress_api, docspec, parquet]
---

# Preserve Explorer data in the shared native release

Give researchers and staff one maintained release with the facts and evidence they use in the older Explorer. Release `e145d24c389e` already ships native meetings, witnesses, videos, channels, recording observations, committee records, and meeting coverage from pinned lake and SpicyRegs inputs. Reuse its verified inputs, release checks, and completed `ct-7uit` archive/catalog work. The public dashboard still selects its separate legacy publication. [e145 release](../docs/releases/2026-11-05-e145d24c389e.md)

The remaining producer work is to preserve unresolved legacy facts, finish the named source corrections, and make refreshes of the Explorer inputs repeatable. Use the frozen comparisons and existing producer entry points. The daily job advances five lake tables while the model carries pinned video and committee-record snapshots and recording decisions. Determine which existing production step advances those pins when qualifying inputs change, and fill any missing handoff. [Field inventory](../docs/plans/phase-2-annex-20261028.md#46-explorer-migration-and-data-coverage) · [Frozen comparison](../docs/measurements/explorer-native-comparison-20261101.md)

## Acceptance Criteria

- Reconcile every retained field and input against the selected release. Include channel and video inventory, matching decisions, completeness and issues, committee amendments and votes, meeting attributes, reference inputs, and SpicyRegs detail. Record each input snapshot, identity, row meaning, missingness, provenance, and destination. Preserve facts and decisions held only in legacy files. Give every omitted, conflicting, or unresolved field or row an evidence-backed disposition. Keep `ct-x78c` responsible for the old witness row ledger.
- Finish the named producer corrections in the existing model. `ct-j78x` owns the shared meeting association for recording evidence. Version the typed fields, keys, and provenance with the producer and registry. Distinguish source facts, inferred matches, and summaries. Use pinned upstream relations for detailed SpicyRegs research and stable evidence references for bulky retained material. Keep identities stable when their inputs and rules are unchanged. Apply the existing value/cause and public link-continuity checks to approved changes.
- Verify the maintained production job selects pinned lake meeting and appearance records, the applicable Explorer refresh outputs, and pinned SpicyRegs generations through native model/export. Compare with frozen old inputs. Reuse exact-match measurements and record runtime, peak memory, objects, and bytes read/written for the affected run under the approved watchdog limit. The native production path must avoid full-corpus legacy JSON/CSV assembly and a 20 GB swap dependency.
- Record source-local, candidate, and delivered evidence separately. Give `ct-t915` and `ct-m104` the same produced release. `cef-96wc` owns the live switch and rollback evidence. `ct-5kto` owns retirement after acceptance.

[November 5 root-cause analysis and source evidence](../docs/plans/production-mvp-root-causes-round2-20261105.md).

## Original design (superseded implementation approach)

1. Migrate the 9 weekly retention state modules (congress_meetings, house_events, senate_events, gpo_hearings, youtube_videos, captions, transcripts, rejected_pages) to incremental docspec-rs tables.
2. Model multi-source Committee Explorer entity resolution (committees, meetings, materials, witnesses, issues, sources) as incremental docspec-rs RefreshSpec AggregateTransform views using FirstValueBy and CollectDistinctWithProvenance (ss-023x), while keeping domain conflict dismissal (_review_old_label_conflict, 'unknown' access transitions, DataIssue emission) in committee_meeting / committee_explorer domain policy.
3. Materialize the 6 browser Parquet tables (committees, meetings, materials, witnesses, issues, sources) via chained RefreshSpec (ss-65bz) + ExportSpec (ss-6gwu), and retire assemble.py's 15.3 GB in-memory accumulator, the 20 GB swap file in publish-explorer.yml, and the legacy .json.gz sharded writer/reader (export.py:556-651, query.py:write_query_partitions, parquet.py:migrate, and apps/site/src/components/explorer/reader/data-source.ts:174-381).

## Audit 2026-10-24

- Verdict: PARTIAL (batch kl2a1aa).
- Grades: proposal 83 → 83, work 66 → 66.
- Problem: The explorer still assembles in Python and re-parses full `.json.gz`/CSV inputs, and removing the old `migrate` import broke Pages deploys for about 2.5 days.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:39
- Status: Reopened: revisit under engine-first rule. Unmet: AC1; the explorer still assembles in Python, writes Parquet itself with docspec only as an optional re-export (`export.py:944-960`), and re-parses full `.json.gz`/CSV inputs. The weekly-mirror part goes with WS10 (ct-r6xw). No plan workstream owns the explorer; linked to the epic ct-98sm for the owner to place.
- See docs/reviews/2026-10-24-ticket-audit/README.md

## Notes

**2026-10-24T18:47:54Z**

Moved under WS7 (ct-7uit). Engine-first: build the Committee Explorer tables with the engine's export, and delete the temporary docspec re-export that is thrown away (export.py:957-984). Folds in the explorer issues from ct-jnw5 (first witness only, saved_copy_sha256 at 0%, lost page indexes), ct-4g55 (export() grew to 687 lines), ct-xx7q (citations re-pointed to records lacking the quoted value) and ct-s9p2 (key source_record ids on content, not the whole-file input_id, so dedup isn't needed forever).

**2026-10-30T17:33:44Z**

Completed Phase 2 F3 in 909b9c72: added apps/committee_youtube/src/committee_explorer/lake_inputs.py and wired --meeting-records, --appearance-records, and --spicy-regs into ExportOptions, export(), reuse.py:request_key(), and CLI main() in apps/committee_youtube/src/committee_explorer/export.py so Committee Explorer reads meeting_records and appearance_records from the lake and committees/members/rosters from spicy-regs (simplification-plan-20261024.md §6.6 item 3, phase-2-annex-20261028.md §4.1). Verified with uv run pytest -q packages/congress_api/tests/test_explorer_export.py apps/committee_youtube/tests/ (98 passed).

**2026-10-30T20:37:05Z**

Reopened and reconciled at the user’s request on 2026-10-30. Current scope and acceptance above supersede the earlier closure where it claimed the remaining Explorer migration was complete. Canonical coverage and order: docs/plans/phase-2-annex-20261028.md §4.6. No implementation, live publication or deletion was performed by this reconciliation.

**2026-10-30T21:20:20Z**

Accepted blind-review prerequisites are ct-sh4j (per-attempt capture eligibility), ct-30fp (contextual witness observations, explicit-empty replacement and occurrence preservation), ct-yymr / ct-kw9b (version handoff/admission), and ct-vpo2 (schemas/invariants). PHASE-2 §4.7 and model/fixtures/manifest.md define the transition cases. Correct these semantics before expanding affected backfills or claiming migration preservation; reuse unaffected completions.

**2026-11-01T10:39:01Z**

Independent Validation Reconciliation (2026-11-01):
- Reopened prerequisite/child tickets `ct-sh4j`, `ct-30fp`, `ct-kw9b`, `ct-wx65`, `ct-h1nd`, and `ct-v51p` with concrete validation findings (Senate repeated witness name deduplication and relative link resolution in `ct-30fp`, candidate-vs-completeness SQL alignment in `ct-kw9b`, 512 MiB HashJoin build-side order and per-attempt conflict/url_state grain fixes in `ct-sh4j`, and edge-case tightening in `ct-wx65`, `ct-h1nd`, `ct-v51p`) so these defects are resolved before final Phase-2 backfill/publication.

**2026-11-01T20:08:14Z**

Owner scope decision 2026-11-01 (annex §4.6, data model §8): raised to P1. Typed release tables for channels, videos, recording matches, completeness and committee amendments/votes. Pinned upstream relations for SpicyRegs detail. Evidence references only for bulky raw material: YouTube caches, captions and per-match evidence files. Nothing is deferred.

**2026-11-02T00:40:43Z**

Owner decision 2026-11-01: revise the memory criterion. Measure and report memory, with a high runaway limit (ct-r8jd) instead of a <2 GB target. Sittings: Congress.gov first and the House fix both (ct-cjwx). Old witness rows are kept (ct-x78c).

**2026-11-02T04:01:45Z**

Code on worktree-agent-a704015cc138b456b @ da425206. Review verdict: merge, stay open. Frozen-input tables built, and 217,794 meeting values compared to raw with 0 differing. Open: byte identity, memory and release ID need a full run; publisher, claims and coverage only restate the rule; coverage disagrees with raw on weak classes such as 1,450 documents and 1,906 witnesses not_stated despite evidence, and the owner decides how to treat them; c.* chain still hits 2 GiB spill at capture_sources. All branches: not merged; parser pins are recomputed once at integration; no backfill, lake write or full model run has happened.

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: coverage. Fix document linking at its source (list.meeting_keys misses 1,450 meetings). Where evidence is held but not yet linked (matcher pending), coverage says unknown, never not_stated. Every present value has a link the user can open.

**2026-11-02T12:28:28Z**

Round 1b 2026-11-02 (lead): Coverage rule (lead decision): a Senate meeting with no linked document or witness is unknown until the Senate page links land; old page decisions are not imported. Same two-way check applies to recording coverage (172 events). impl-f.

**2026-11-02T13:22:51Z**

2026-11-02 impl-f (r1b-f, 12 commits): Senate meetings unknown until page links land; 7,837 caption coverage rows go from not_stated to unknown. Evidence: docs/measurements/meeting-semantics-raw-check-20261102.json on r1b-f.

**2026-11-02T15:31:02Z**

2026-11-02 impl-u2 (r4-u2 925036be): the production model job now takes pinned spicy-regs generations as a declared input; the producer made up sha256('spicy-regs:<family>') digests since 959c23ee, which went into the input record, manifest and pin file. All 12 tables are pinned under the six generations the live release uses (amendments 75c96edc, bill-family f719442c, committee-rosters 5f031073, members 29718daf, nominations d17c43e1, roll-call-votes e7cdd80d), each root recomputed and every file matched. Using live's generations keeps gate 1's differences attributable to the fixes; newer generations are a follow-up. Inputs: .cache/archive-release/r1b/inputs/spicy_regs/. Lane 10,804 passed. F4 holds once this merges.

**2026-11-03T22:53:52Z**

Progress update 2026-11-03: Release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd is LIVE at https://congressional-data.spicygov.ai/viewer-publications/manifest.json (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419). All 5 publish gates passed (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), 7 gated lake snapshots exported and imported to Basin with producer proofs, full production-offline lane passed (10,967 passed on release-train), contract:archive and live canary:archive passed, and congressional-explorer-mcp (v0.5.1, 22 tables) verified live against the published pointer.

**2026-11-04T15:08:32Z**

2026-11-04 persona investigation ticket reconciliation (GPT-6.1 Sol, xhigh): all 61 partial/blocked cases were investigated against selected release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd. Nine bounded tasks completed; remaining work separates source/data gaps, maintained recipe defects and incorrect caller assumptions. Source inspection observed HEAD 730a2d8e0c55880fc058d13cc74d265fc315f41f, separately from the unchanged served release.

Existing owners updated: ct-dx22 reopened for within-print witness sitting-date misassignment (July 12 witnesses assigned June 2); ct-9479 remains open for published superseded panels versus the local filter; ct-nh41 for recovery-note provenance; ct-m94a for unqualified live date/Congress bounds; ct-8cno for missing historical roster data; ct-mx3g for misleading roster wording. Prior fixes and historical evidence remain intact.

New focused tickets: ct-lx67 (comma-containing job titles leak into organization); ct-j78x (package-linked recording observations omitted by event-only recipes); ct-j49p (supplied nomination committee activities dropped); ct-717p (trace event 118300 missing committee-record input before export). ct-717p is an investigation with an unproved source-admission cause, not a claim that the parser dropped a frozen captured body.

Do not reuse the prior '3,883 bills' denominator: it counted literal source labels, including amendment ordinals/placeholders. That corrected ad-hoc query mistake does not need another implementation ticket. The bounded 306/2,256 recognized-label/meeting-subject result is not the complete bill population. Likewise, intentional single-release limits, absent global full-text indexing, unsupported person identity and licensing inferences are not newly asserted defects.

Acceptance remains at the owning source/model/registry and actual delivered release: an MCP reinstall cannot fix old published data or recipes. No code repair, data refresh, tests or publication occurred in this ticket pass. Reproduction identifiers and narrow acceptance criteria are retained in each ticket. Full issue mapping and evidence: .cache/archive-release/chaos-personas-20261104/investigation-report.md and ticket-{accountability,legislative,discovery}.json. No new blocking dependencies were inferred from related context.

**2026-11-04T15:26:35Z**

Coordinated root-cause remediation plan (2026-11-04): docs/plans/congress-explorer-root-cause-remediation-20261104.md. This is planned work and ticket reconciliation only, not implementation/publication evidence. Preserve this ticket's inventory/native-model role, existing history and open status.

The existing owners now share explicit meanings and release criteria. Appearance binding leaves multi-date print witnesses package-scoped unless existing occurrence evidence supports a sitting (ct-dx22); shared extraction preserves affiliation ambiguity (ct-lx67); recording_matches gains producer-owned meeting_links with direct_event/print_agreement basis and event/package_context scope for shared coverage/recipes/site (ct-j78x). No bare all-transcript join or copying a recording to every sitting. Current default appearances use superseded_by without deleting source history (ct-9479). Nomination supplied activities retain committee groups, exact labels/date strings, null/empty distinctions and multiplicity (ct-j49p). Recovery-note repair preserves immutable decision history (ct-nh41). ct-717p first traces the one frozen input chain before choosing a repair. ct-m94a/ct-mx3g finish truthful qualification/wording; ct-8cno still requires its upstream historical generation, without blocking truthful wording or independent fixes.

Root causes are corrected at their owners: no new general relationship engine, second MCP model, global corpus audit or speculative source acquisition. Source meaning/fixtures can develop in parallel; one editor integrates shared registry/model declarations/generated references/native fixtures. Hard prerequisites are inside each work package and before its consumer/data release; shared-file serialization is not a dependency among unrelated fixes. Completed corrections may form a qualified candidate without pretending unresolved/acquisition-dependent work is complete. All excluded or unresolved facts remain in this inventory.

Reuse identity-valid retained inputs/results. A changed parser requires its actual digest closure, one selected source version, exact predicate proof or measured family replay, coherent pins and authoritative lake/catalog continuity. Record changed occurrence keys and document-witness links in gate-1 causes; gate-2 public document redirects are separate. Existing gates, native fixtures, stdio/site checks and rollback path remain. Each heavy job needs measured watchdog admission; no new cost/performance guarantee is asserted. Use fresh owned pytest attempt directories because explicit basetemp is recursively removed.

Completion has three separately recorded boundaries: source-local truth, candidate/publication, installed/site selection. ct-m104/ct-t915 carry corresponding acceptance; cef-96wc remains live-switch ownership. No reinstall repairs old immutable data, and no ticket closes merely because local source or counts look correct. The full plan and owner tickets name source evidence, acceptance cases, exclusions and dependency distinctions.

**2026-11-05T17:11:15Z**

Consolidation preserves this as the active congressional producer owner. ct-7uit's earlier archive/catalog implementation and G01/G02 deletions are historical completed work; its only remaining Explorer migration is carried here. Keep exact retained input/field inventory, per-row preservation/dispositions, stable source/document identities, real native production bindings, and measured parity/resource use without legacy full-corpus JSON/CSV assembly or swap dependence. ct-t915/ct-m104/cef-96wc/ct-5kto remain distinct site/MCP/live-switch/retirement owners. Use the maintained value/cause and link-continuity release checks, not historical storage-transition totals as a permanent population freeze.

Consolidation accepted 2026-11-05: absorb ct-7uit.

User outcome: One owner for the remaining Explorer producer migration.

Remaining acceptance: Completed archive/catalog and G01/G02 evidence; full retained-field inventory; row dispositions; actual native job bindings; measured comparison. Repoint umbrella dependencies to ct-gi01.

Source evidence and full original criteria remain in: .tickets/ct-7uit.md:26; .tickets/ct-gi01.md:46; docs/plans/phase-2-annex-20261028.md:481. The superseded records remain available; completed work is reused and unfinished criteria stay with this owner.

**2026-11-05T21:33:58Z**

`373ebb96` adds opt-in video refresh through the existing daily producer. Fresh independent acceptance on `dd9a6f82` verified the default path, a native append, reuse of the same pin on an unchanged run, and the HTML and video pin handoffs in fresh and resumed publication. The Gate 1 link-attribution correction `9c3ee247` merged at `5aa78701` and passed its independent planted case. The merged nightly implementation and acceptance worktrees and branches were pruned with their exact tips archived. [Independent acceptance](../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/acceptance/nightly-freshness/REVIEW.md)

Keep open for activation of qualified video, committee and playlist targets, generation and import of qualified recording decisions, and the broader Explorer migration. Production acceptance still needs exact refreshed native bindings, retained-field and row accounting, measured comparison with frozen legacy inputs, and delivery of the common release to both readers.

**2026-11-05T23:55:26Z**

Wave 1/2 implementation closure handoff: source changes and requested independent acceptance are complete for ct-dx22, ct-lx67, ct-j78x, ct-j49p, ct-67k1, ct-opy0, ct-j9o7, ct-cxc5, ct-717p, ct-k2ij and ct-db3w. Those tickets close as implementation; this ticket retains their combined-model and publication obligations. [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md)

The coordinator must run all six invariant suites and the existing comparison/cause/link checks, then verify: Farmer/Reese keys and affiliations plus the separately traced July link; recording meeting_links and Altman package context; PN1011 activity precision; publisher-reference multiplicity; chamber_basis and 104064/119583; supported H.R. 2899 identity; the three cover dates; Rules 118300’s 31 children; House committee links; and the five recovered meeting IDs with the other three documented dispositions. ct-r4rd retains the full SpicyRegs comparison and unmerged upstream comparator handoff.

The native imports, 12-receipt append and seven canonical daily writer targets are now verified; committee and playlist activation are no longer outstanding. Retain the broader legacy field/row inventory, qualified recording-decision production, opt-in video follow-through and source gaps, including the 292 House signals outside the bounded batch. ct-m104 owns paired reader acceptance and cef-96wc owns live cutover. Closing implementation tickets does not mark these release checks passed.

**2026-11-06T17:38:34Z**

Residual migration inventory and retained-native acceptance completed locally on isolated branch codex/ct-gi01-preservation-20261106 (base 742dbe70). The report inventories all six retained Explorer table schemas, all 16 frozen CSVs and three reference inputs: 291 field dispositions, 878,151 non-witness row references and 417,004 individual material-file references. All CSV hashes match the earlier frozen comparison. All 7,200 curated source rows preserve every original CSV field through the exact pinned decision file and their exported native subjects/verdicts/references. The nine-column committee comparison matches 19,984/19,985 rows; the sole encoding correction at event 115405 matches after repairing the independently adjudicated mojibake. No unexplained amendment loss was found.

The retained completed-model checkpoint, manifest and all eight native selectors/parser pins match candidate 720c495b and main 742dbe70. Candidate SpicyRegs manifest 7188109e predates main 4adb1f42 and its added detailed action/member-vote tables; this is not final-main or deployed acceptance. The inventory ran in 49.6 s at 0.671 GiB RSS. Focused tests cover lost source-only fields, wrong verdicts/digests, duplicate rows, partial URL coverage, null/empty differences and historical adjudications. Full details: docs/measurements/explorer-preservation-inventory-20261106.md; durable results: .cache/archive-release/implementation/reviewed-non-news-20261106/ct-gi01/.

Keep open: typed retained scored-matcher observations are absent; the 312 unmapped old meetings are Senate-page observations requiring supported association or a source-observation destination, not 312 proven missing hearings; URL/value/association gaps remain per material-file ledger; historical reference facts need typed destinations; original issue-decision JSON/raw-body custody remains distinct from 7,502 retained source records. Historical issue dispositions account for all 35 classes without erasing curator dismissals. Daily already names seven writers; committee/playlist activation is completed, while video deliberately stays opt-in and recording decisions pinned. No producer/catalog/raw write, model rebuild, acquisition, pointer/deployment, schedule change, push, main merge or cleanup occurred. ct-x78c, ct-r4rd, ct-8cno, ct-m104 and cef-96wc retain their separate ownership.

**2026-11-06T18:43:09Z**

Local inventory and retained-candidate checks are complete at a020be98: 291 field dispositions, row/file ledgers and durable frozen inputs. All 7,200 curated decisions preserve source fields and native values; 11 focused checks passed. The completion recheck preserved that commit and reused qualified results. Of 312 source-only Senate pages, 294 have native document context and 18 have no literal context match; none gains an event key through those links. These are qualified local findings on private candidate 720c, not live delivery. Evidence: ct-gi01/HANDOFF.md and completion-recheck.json in the reviewed-non-news-20261106 cache.

Keep open. The root rollup/shared model owner must integrate an inference/source-observation input that preserves methods, scores and history without labeling them curated or changing absence meaning; ct-gi01 retains preservation requirements. ct-m104 owns final build/deployment and paired readers; cef-96wc owns cutover. Material/reference/custody gaps remain recorded. Committee/playlist activation is already complete; video remains deliberately opt-in. No new source commit, shared write, competing build, merge or publication occurred.

Independent reviewer /root/four_skill_review read all four requested skills and APPROVED unchanged a020be98: no scoped defect or source repair requested. The static review confirmed checkpoint/input identities and retains explicit test/data/live limits; see merge-prune-20261106T180951Z/reviews/ct-gi01/REVIEW.md.

Independent review: APPROVE for the scoped work; remaining ticket acceptance is unchanged. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-gi01/REVIEW.md).

**2026-11-07T22:39:10Z**

November 7 post-release owner update for archive `5d24699ad9fa` / Explorer `0.6.2`. Keep `ct-gi01` open. The native build, paired delivery, live switch and deployed retirement have retained acceptance evidence. This pass reconciled all 78 release change groups and 291 retained fields, recovered the exact October matcher input and two committee-review inputs, verified all 7,200 curated decisions, and found published document keys for 294 of 312 legacy Senate pages. Four installed-reader probes passed; no hosted requests or source changes were made.

The remaining work is specific: publish historical matcher observations with their original meaning; resolve the 18 source-only Senate pages; reconcile 9,636 URL-unmatched material occurrences and retained field values; verify historical reference values; and establish the original dismissal-input/body custody or record a supported disposition. `ct-x78c` retains witness-ledger ownership and `ct-r4rd` retains meeting-field ownership. Reuse the shipped-release evidence for unchanged inputs. This update establishes no new closure or rebuild requirement.

[Owner results](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-gi01/RESULTS.md) · [Owner status](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-gi01/STATUS.json).

**2026-11-08T13:44:49Z**

2026-11-08: the 2026-11-02 impl-u2 note's 'F4 holds once this merges' no longer waits on r4-u2 (925036be), which will not merge. Main reached the same goal: model/jobs/publish-model.json declares a spicy_regs input pinned by path, sha256 and size, and archive_model._prepare_spicy_inputs refuses entity files without pinned generations, so no digest is invented. Judge F4 against main.
