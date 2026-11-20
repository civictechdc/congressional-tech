---
id: ct-fb29
status: closed
deps: []
links: []
created: 2026-11-18T20:27:36Z
type: task
priority: 2
assignee: mikewolfd
tags: [docs, mcp, schema]
---
# Give visitors and MCP agents plain descriptions of datasets and nested fields

Commit 8bbedc89 on archive/2026-11-18/codex/ddk-congress-replacement-20261106 wrote 23 dataset introductions and meanings for nested fields (detail.main_content.*, detail.page_metadata[].*, members.cross_ids.*, bills.floor_votes[].*) that model/registries/release-schema.json on main lacks; get_dataset_info and the site would show them. 395 of 437 descriptions already sit in DDK's catalog.ddk.json; 42 exist only on the branch. Port into release-schema.json and send the 42 to DDK. Check first whether release-schema.json is in the model definition hash. Review: .cache/archive-release/reviews/branch-value-20261118/b-ct-ddk/REPORT.md.

## Acceptance Criteria

get_dataset_info returns a description for every published dataset and nested field.


## Notes

**2026-11-20T17:29:40Z**

2026-11-20: Ported all 31 dataset description introductions and 248 nested/element notes into model/registries/release-schema.json, wired get_dataset_info in apps/explorer_mcp and docs/release-relationships.md, and verified ../data-design-kit catalog.ddk.json (437/437 JSON-equal). Verified in Validate Congress MCP (44776340177), Deploy website to Pages (44771988070), and Validate Committee Explorer (44776340037); awaiting archive-jobs.yml publish readback to close.

**2026-11-20T19:55:13Z**

2026-11-20: Live in production release 0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3 (publish run 44802939293, published_at 2026-11-20T19:46:43Z). Read back viewer-publications/releases/0e7084cde775.../schema.json from R2: all 31 dataset description introductions and 248 nested/element notes verified live.
