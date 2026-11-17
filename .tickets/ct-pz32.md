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

