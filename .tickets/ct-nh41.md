---
id: ct-nh41
status: open
deps: []
links: [ct-zkzt]
created: 2026-11-04T02:45:03Z
type: bug
priority: 3
assignee: mikewolfd
tags: [publication, recoveries, mcp, chaos-test]
---
# recoveries.identity_note publishes pipeline provenance instead of an identity explanation

release-schema.json declares recoveries.identity_note as 'Explanation identifying the recovery', but in release e4538f00 every row is either the pipeline string 'Reconciled from pinned accepted mappings <sha256>; receipt categories preserved' (12,391 rows) or NULL (227). No row explains how a recovery relates to the original. The string comes from packages/corpus_recovery/src/corpus_recovery/reconcile.py:164, and the pin it embeds is already published separately as evidence_sha256. The site already treats it as noise: cleanIdentityNote in apps/site/src/components/explorer/archive/archive-metadata.ts maps it to null (pinned by archive-presentation.test.mjs and archive-unit.test.ts). The MCP passes it through raw, and get_document tells agents that 'a recovery's kind and identity_note explain its relationship', so agents read pipeline provenance as an identity statement. The relationship is actually carried by kind (recovered_document, official_updated_revision_available, ...). Found in chaos run chaos-congress-mcp-20261103 and confirmed in review.

## Acceptance Criteria

Published identity_note is either a human-readable explanation of the recovery's relationship to the original, or NULL; reconciliation provenance stays in evidence_sha256 (or a separately named provenance field), not in identity_note. The schema meaning matches what is published. Once the release no longer emits the string, the site's cleanIdentityNote special case is removed rather than duplicated in the MCP. The get_document description states which field carries the relationship. A publication test on fixed recovery inputs proves no identity_note contains reconciliation provenance.

