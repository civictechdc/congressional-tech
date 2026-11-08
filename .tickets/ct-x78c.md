---
id: ct-x78c
status: open
deps: []
links: [ct-kthe, ct-j2yo, ct-5w9u, ct-dx22, ct-egg6, ct-m104, ct-t915, ct-5kto]
created: 2026-11-02T00:40:43Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [explorer, witnesses, phase2]
---

# Preserve distinct witness appearances and account for legacy rows

Researchers should retain the witness roles, documents and links supported by the original sources when the old Explorer retires.

In event `100520`, one House witness list records W. Ron Allen in two active roles. One represents the Jamestown S'Klallam Tribe and the other the Pacific Salmon Commissioner. The entries have the same publication time and separate biographies and statements. Release `e145d24c389e` preserves both rows, but the model marks key `2a0208241fb6a49d` superseded by `db779668e63d56bb`. The prior same-list rule used name and XML order and missed the distinct roles and document evidence. Default readers that rely on the published marker can omit the second role.

The older comparison's 19,475 groups combine rows by event and normalized name. Those groups help find cases and cannot establish that each distinct legacy appearance or role survived. House receipt-path binding already works for at least the exact published `meeting:100346` case, Stephen T. Ayers, key `e0ca0e7375ff80be`.

## Implementation and remaining checks

The first-wave merge `18049548` includes the narrow same-list fix (`2b130952`). It preserves roles with distinct source evidence and still collapses repeated entries that agree on their role, panel and document links. The 74 focused model checks passed, including repeated entries and distinct panel and document controls.

The digest-checked House XML gives both W. Ron Allen roles in event `100520` a biography and a statement link. The bounded native check kept both keys active and assigned all four source-listed links to their respective roles. The installed MCP baseline on `e145` carries three of those four documents.

After the build hold clears, the release coordinator will verify both roles, the available documents and the receipt-path control at event `100346` on the same selected site and MCP. The broader legacy audit remains open. Use frozen source evidence to account for each distinct legacy occurrence, with a reason and owner for gaps. [Site](ct-t915.md) · [MCP](ct-m104.md) · [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md)

## Acceptance Criteria

- The `100520` source case preserves both active roles and their distinct document links. Existing duplicate controls, exact historical keys, genuine repeated occurrences and the testimony versus statement distinction still work.
- Every distinct legacy witness row has a supported migrated occurrence or a named reason and owner. Count proven duplicate rows once and identify unread and unavailable records separately.
- The site and MCP demonstrate migrated House witnesses on the same selected release, including the receipt-path case at `100346`. Record release identity and evidence. [ct-5kto](ct-5kto.md) keeps legacy retirement conditional on the full result.

Evidence includes the retained House XML digest `84b319d68aea2a55393ea355e682c4e672614dbca9e67802cac7bfa0da1c9ea7`, `model/sql/witness-precedence.sql` and the [legacy comparison](../docs/measurements/explorer-native-comparison-20261101.md).

[November 5 root-cause analysis and source evidence](../docs/plans/production-mvp-root-causes-round2-20261105.md).

## Notes

**2026-11-02T04:01:45Z**

Final review correction: all 976 docs.house.gov rows are in raw witness XML (226 bodies), parsed in appearance_records, but 225 have NULL event_id. Rows have no URL; receipts' original_path wlist/{event}.xml states it. The 98 searched meeting XML only. 19,475 distinct rows; 849 and 1,300 are named with owners, not migrated. Code on worktree-agent-a704015cc138b456b @ da425206. All branches: not merged; parser pins are recomputed once at integration; no backfill, lake write or full model run has happened.

**2026-11-02T13:22:51Z**

2026-11-02 impl-f (r1b-f, 12 commits): 187 House witness lists attached; the old Explorer witness ledger's rows attached to their meeting go from 11,779 to 12,856; 40 path-only lists need e1's captures.original_path (f's last commit fails at planning until e1 merges, deliberately).

**2026-11-02T13:43:11Z**

2026-11-02 green-f: 187/187 House lists attach via their own receipt path (827 rows); 40 lists (190 rows) wait on e1; no site or MCP check of the migrated rows yet (requested).

**2026-11-02T15:10:29Z**

2026-11-02 red-f2 (BLOCK, narrow): the per-person precedence rule also protects old witness rows: a lower-ranked row survives unless it matches someone on the higher-ranked list for that meeting.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.

**2026-11-04T02:21:36Z**

Reopened 2026-11-03 (post-release acceptance test): witness churn is categorized (explorer-native-comparison-20261101.md), but the per-row disposition ledger against live e4538f00 and a site/MCP check of migrated House witness rows are not recorded. r3-site (unmerged) carries the archive reader for the Explorer families.

**2026-11-05T20:18:07Z**

Integrated the narrow same-list precedence repair at 2b130952. The exact event 100520 House XML supports two active W. Ron Allen roles with distinct biographies and statements; both existing keys remain active. Seventy-four focused native tests passed. Root independently checked all four source links and rejected planted wrong-suppression and wrong-role results. The full legacy occurrence audit and same-selected-release site/MCP checks remain open. Full build/publication waits all waves.

**2026-11-06T16:55:10Z**

Completed the bounded occurrence ledger at docs/measurements/legacy-witness-occurrences-20261106.md: all 36,301 frozen CSV records and original fields survive with a disposition and owner against private candidate 720c495b. Candidate field matches are distinct from verified migration. No duplicate verdict is inferred from identical text; the Jefferson Keel same-list control preserves representation and links. Thirteen focused project-runner checks pass (partial lane); final ledger 4.2 s, 0.505 GiB RSS. Reused merged 2b130952 and its 74 native controls. All five named Allen/Keel/Ayers candidate keys are active; exact reader cases and shared-biography caution are in the durable ct-x78c/reader-handoff.json. New exact House residuals: twelve records for six witnesses at 100876 are present in retained seven-witness XML but absent from the selected one-witness source; nineteen No, but took Oath literals need fuller treatment than the native boolean. Raw non-House bodies, population-wide name correspondence and document-link flags remain explicitly unresolved with owners. Ticket stays open for those dispositions and same-final-release site/MCP acceptance. No model rebuild, shared-data write, merge, push, publication or deployment.

**2026-11-06T17:19:33Z**

Merged the independently accepted historical MODS redirect repair at `c5d8fe9bbafaccd421f572ba8fe1bc745d9f8282` into local main and pruned its owned worktree. All 1,420 diagnosed former published keys and ten older aliases resolve to their expected package-scoped successors. All 153,390 existing mappings/statuses and current witness rows remain unchanged. Farmer/Reese historical June keys now redirect to their package occurrences; false Stiefel keys remain absent. Eighty-two focused native tests and independent exact-commit native replay pass; five deliberately corrupted results were rejected. This is not a full lane or selected-release result. Evidence: `.cache/archive-release/implementation/production-mvp-20261105T190929Z/combined-release-prep/cause-review/repair/HANDOFF.md`. The broader source-occurrence ledger and same-selected-release site/MCP acceptance remain open with their existing owners.

**2026-11-06T18:43:09Z**

The local ledger at 9b79f6bf preserves all 36,301 frozen witness records and original facts with dispositions/owners; 13 focused checks passed (partial lane). Ticket-only ad54f567 credits the separately merged historical-key repair c5d8fe9b. Follow-up checks confirm all 7,939 detailed House name-component correspondences and nineteen raw oath literals. Accepted Allen evidence proves four source URLs resolve to three bodies with correct role sets.

Correction: event 100876 is an actionable source-admission defect, not merely a choice between authentic historical rosters. The selected one-witness body exactly matches a test fixture and entered through manual-source-review normalized/model files in two retained receipt lines; the independent original has seven witnesses. Root owns the bounded eligibility/input repair, preserving raw history and normal list replacement; do not union rosters or infer testimony. Exact receipts/capture rows and correction: ct-x78c/SOURCE-ADMISSION-HANDOFF.md and closure-audit/historical-appearance-decision.md. The four-skill independent review is running at /root/four_skill_ct_x78c_review. Keep open for that repair, remaining occurrence/oath/link dispositions, and ct-m104’s final native/site/MCP acceptance. No reviewed source or selected release changed here.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at d2e4b9fe. The witness ledger preserves all 36,301 originals and refuses unproved positional evidence mappings. Eighteen focused checks passed; 20 positions remain explicitly unqualified. A separate independently approved eligibility repair at 95f78bcf prevents two manual receipt contexts from winning current roster authority or re-entering through failed/expanded contexts. Its bounded native consumer selects all seven original occurrences while preserving authentic newer/empty replacements and qualified identical-byte contexts. The repair passed 25 author and 10 independent checks; 12 affected legacy rows map to six restored occurrences.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Canonical ledger reconciliation, remaining occurrence/oath/link dispositions and final selected native/site/MCP acceptance. Separate eligibility evidence is in house-roster-eligibility/HANDOFF.json beside this review folder. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-x78c/REVIEW.md).

**2026-11-07T20:35:49Z**

The published archive release `5d24699ad9fa076e3e10c894a1cb3310ab35b12e8025adcca87feca7978080c1` carries the reviewed witness-key and source-position changes. The live site opened the corrected Tony Crasi entry from the selected release. The release comparison retains the supported legacy redirects and records the exact exceptions.

Keep this ticket open for the three package-scoped source fields now visible after removing unsupported precedence links.

- `b60b1f935df8698b`, `CHRG-106shrg66376`, `mods:witness[25]`. Ella Wong-Ruskinko's position contains the recipient wording “to Senator McConnell.”
- `de27460db30117e6`, `CHRG-112jhrg85228`, `mods:witness[25]`. Cindy McKim's organization text continues into separate people.
- `ffc8f75925cd3378`, `CHRG-113shrg89525`, `mods:witness[6]`. Victor Joseph's organization text continues into Michael K. Abbott's title and employer.

The three package entries have no assigned hearing event. The original `Senator Smith` contents line at `CHRG-106shrg66376`, `mods:witness[17]`, still does not establish an entry type or a unique person. Twenty-one documents retain empty role-specific witness associations because the sources do not identify one of the competing roles. Wider historical affiliation cleanup remains open.

[Selected archive manifest](https://congressional-data.spicygov.ai/viewer-publications/releases/5d24699ad9fa076e3e10c894a1cb3310ab35b12e8025adcca87feca7978080c1/manifest.json)

**2026-11-08T14:11:27Z**

2026-11-08 activated (owner approved in chat; Claude session took over from Codex): the qualified 44,838-row generation (35,020 MODS at 1d57eb44, 9,818 Senate at 9d48c0f6) is the appearance_records head. Snapshot 5528396916047211530 -> 2797270525889091387 via daily.activate_appearance_generations from clean source 6531d60c, under the nightly writer and release-mutation locks. All 7 other selectors unchanged; native producer chain verified; pending work 0 (plan sha 68dbb105, same as the last verified plan). Watchdog peak 2.35 GiB, 90 s. No publication started; the public pointer still names 5d24699ad9fa. Report: .cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-x78c/activation-claude-20261108/activation-complete.json (script activate-x78c-claude-20261108.py beside it). Remaining: combined release build, gate-1 causes, and same-release site and hosted readback of the four corrections.

**2026-11-08T15:26:16Z**

2026-11-08: published in archive release 63016450530114d8ebc03d2936dc8293250ffd546bf00d5205909345216e5e78 (public pointer moved; browser contract and public canary passed; hosted Explorer re-pinned in aed605d1 and read back). Causes: model/jobs/release-causes/5d24699ad9fa-630164505301.json; note: docs/releases/2026-11-08-630164505301.md. Hosted readback: Ella Wong-Ruskinko is record_material; McKim organization corrected. Independent second review confirmed exactly 4 value changes plus the Joseph supersession.
