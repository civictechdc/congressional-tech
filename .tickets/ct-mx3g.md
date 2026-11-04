---
id: ct-mx3g
status: open
deps: []
links: [ct-8cno]
created: 2026-11-04T02:25:37Z
type: bug
priority: 2
assignee: mikewolfd
tags: [publication, coverage, chaos-test]
---
# rosters coverage gap note claims 113th-119th but release publishes 119th only

rosters.parquet coverage publishes congress_start=119 and congress_end=119, and all 2,973 rows are congress 119 (verified on release e4538f00), but the gap string reads 'Committee seats cover the 113th-119th Congresses only'. The upstream committee_assignments limits text gets the framing right ('Schema supports 113th-119th Congress committee and subcommittee assignments; currently populated for the 119th Congress in the pinned upstream snapshot') — the rosters gap note should agree with the published rows or state the schema-support vs populated distinction. Discovered via chaos run chaos-congress-mcp-20261103 and confirmed in review.

## Acceptance Criteria

The rosters gap note agrees with the published coverage values for a fixed fixture (both directions: a release genuinely spanning multiple Congresses, and the current 119-only one). A publication test asserts note text consistency with coverage values.


## Notes

**2026-11-04T15:07:16Z**

2026-11-04 accountability investigation: local correction exists; live metadata is unchanged. Live release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; checkout inspected separately at 730a2d8e0c55880fc058d13cc74d265fc315f41f. This is ticket-only follow-up to chaos-personas-20261104; no repair, tests, source regeneration or publication was performed. Fresh runtime schema is retained in .cache/archive-release/chaos-personas-20261104/ticket-accountability/runtime-check.json.

Fresh get_dataset_info returns rosters coverage congress_start=119, congress_end=119 and gap 'Committee seats cover the 113th–119th Congresses only'. Prior independent Parquet reading on this same immutable release found all 2,973 roster rows in Congress 119 (.cache/archive-release/chaos-personas-20261104/independent-table-audit.json). The pinned upstream relation independently states schema support for 113th–119th but population for 119th only.

At the inspected checkout, model/registries/release-schema.json:1163 already says 'Committee seats cover only the Congresses populated in the pinned upstream committee_assignments snapshot; congress_start and congress_end give the published range'. This is prepared local source, not live delivery; no fixture/test result is claimed by this note. Ownership stays with shared release metadata/publication, not a separate MCP wording workaround.

Smallest remaining acceptance: retain fixture checks for single- and multi-Congress snapshots, publish the qualified corrected metadata through the existing release path, and read get_dataset_info from the installed target to show wording agrees with the actual selected range. This wording fix need not wait for historical data acquisition. Preserve status open; no closure from source inspection.

**2026-11-04T15:23:03Z**

Coordinated producer plan frozen 2026-11-04: docs/plans/congress-explorer-root-cause-remediation-20261104.md. This addendum refines remaining work without rewriting prior evidence. Live evidence remains release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; source inspected at 730a2d8e0c55880fc058d13cc74d265fc315f41f. Planning/ticket update only: no implementation, tests, prepare, acquisition, data changes or publication.

Owner: shared release coverage/schema publication. Keep one truthful meaning for site/MCP: roster congress_start/end state the populated pinned snapshot span, not every Congress the schema can support. Current registry:1163 already contains the local corrected wording; e4538f00 still advertises 113th-119th wording over 119-only rows. Do not add separate reader-specific wording policy.

Smallest remaining checks are maintained fixed fixtures for 119-only, multiple populated Congresses and unavailable/empty history with distinct meanings, then actual emitted metadata and generic-reader discovery. Do not treat missing roster history as zero committee seats or claim complete normalization. This is a metadata correction that can proceed independently of ct-8cno/ss-ehci history acquisition; no source/parser replay is required merely to publish accurate wording. Keep the existing release path and exact metadata/data identity policy, and verify the actually selected installed release before closure. Local schema text and plan notes are prepared work, not delivered repair.

**2026-11-04T17:19:35Z**

Merged 919258e7 to main (rebased from 1b9ecfc9). Pre-rebase full lanes on 1b9ecfc9: production-offline (full lane): exit 0 (11,357 passed), explorer-mcp (full lane): exit 0; after rebase onto aaaf6f28 (disjoint files), test_phase2_model_entities.py 26 passed (partial). Fixture checks tie rosters congress_start/end and every roster text to published rows for 119-only, 113/116/119 and empty snapshots; planted old note refused. Open until a published release carries the new note and get_dataset_info from the installed release agrees with its rows.
