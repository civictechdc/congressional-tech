---
id: ct-x78c
status: open
deps: []
links: [ct-kthe, ct-j2yo, ct-5w9u, ct-dx22, ct-egg6, ct-m104, ct-t915]
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
