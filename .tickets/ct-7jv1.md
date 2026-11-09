---
id: ct-7jv1
status: open
deps: []
links: []
created: 2026-11-09T15:50:38Z
type: feature
priority: 3
assignee: mikewolfd
---
# Say in meeting results whether captions are archived or only advertised by the publisher


From the 2026-11-09 hosted MCP audit: 195 meetings report publisher caption availability (mostly YouTube metadata) but hold no retained caption track, and 3 claim a video association without a retained recording. The auditor withdrew the bug once the distinction was clear, and asked that the API state it. Proposal: expose the existing distinction as a named field on meetings and hearing bundles (for example captions: {advertised: true, archived: false, basis: ...}) so transcripts[] being empty is self-explaining. Data already exists; no new capture. Tags: mcp, mcp-audit-20261109.
