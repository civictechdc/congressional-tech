---
id: ct-pz32
status: in_progress
deps: []
links: []
created: 2026-11-17T08:49:41Z
type: task
priority: 1
assignee: mikewolfd
tags: [hosted, mcp, ci, publish]
---
# Hosted MCP follows the live archive pointer; nightly chain runs unattended

Owner 2026-11-17: everything runs automatically from now on. After ct-b1jj the hosted nightly is capture (schedule) -> publish (workflow_run), but each release still needed a hand edit of PUBLICATION in apps/explorer_mcp/cloudflare/wrangler.jsonc plus a wrangler deploy (d1b8a0b5, 72b62edb), so the hosted MCP would fall one release behind every night. The workflow_run trigger itself had never fired: all five hosted publish runs were workflow_dispatch.

## Acceptance Criteria

The Worker resolves the immutable manifest from the moving pointer itself (each container still pinned to one immutable release, named after it); no per-release commit or deploy. One capture-triggered (workflow_run) publish finishes green, and the hosted MCP /ready names the pointer's release afterwards without a deploy. The archive workflow fails visibly when the hosted MCP does not follow.


## Notes

**2026-11-17T09:40:00Z**

Done and verified:
- Hosted MCP follows the pointer (33ac5fc4; Worker version f67e0bec, max_instances 4). `GET /` and `/ready` name 6ac86c21b373 with no release in wrangler.jsonc; smoke.py passes; a cold start through the new Worker took 53 s. The publish job's last step compares hosted `/ready` with the pointer.
- A cause record whose candidate is live no longer refuses later nights (18ebf957).
- The workflow_run trigger fires: capture 44049858500 (workflow_dispatch, green, 16m51s) started publish 44052307169 on 18ebf957 with no dispatch.

Not met: that publish built candidate c998ffa0766f (1,307 s, 10.08 GiB peak) and stopped at gate 1 with 42 groups. Evidence: `.cache/archive-release/hosted-runs/44052307169/`. Measured:
- The model definition is identical to the live build's (`profile_sha256` 5cd6fc7850d2 in both completed-model.json files); only lake snapshots differ, so every difference comes from the night's 1,173 new receipts. Link rule clean (0 missing, 0 dangling).
- The automatic proof (ct-ud0b) covers additions only and at most 250 documents. This one capture added 478 documents and changed existing rows: 1,097 titles, 287 committee_keys, 1,934 source link texts, url_state attempts, 81 meeting-coverage counts.
- All 42 refused group ids are in the last accepted record (4b9a7bd126cc-6ac86c21b373); 39 are in the 2026-11-13 capture-night record. All 13 releases since 2026-11-03 carried a hand-written record: no capture night has ever published unattended.

So the chain runs by itself up to gate 1 and stops there every capture night. What may pass gate 1 without a person is the owner's decision (asked 2026-11-17).
