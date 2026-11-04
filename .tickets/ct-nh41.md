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


## Notes

**2026-11-04T15:07:16Z**

2026-11-04 accountability investigation: confirmed on the unchanged live release. Live release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; checkout inspected separately at 730a2d8e0c55880fc058d13cc74d265fc315f41f. This is ticket-only follow-up to chaos-personas-20261104; no repair, tests, source regeneration or publication was performed. Fresh runtime schema is retained in .cache/archive-release/chaos-personas-20261104/ticket-accountability/runtime-check.json.

Independent selected-Parquet export, cross-checked against MCP, contains all 6,546 documents with saved_kind='recovery' and their 7,314 recovery occurrences. Of these occurrences 7,127 identity_note values begin 'Reconciled from pinned accepted mappings '; 187 are NULL; none gives a human identity explanation. These are the recovery-backed subset, not a replacement for the ticket's release-wide 12,618-occurrence count. The complete inventory includes immutable release/link references, raw notes, kind, recovery body, URL and suffix: .cache/archive-release/chaos-personas-20261104/investigation-accountability/recovery-documents.jsonl. Counts/read columns/timing: local-audit-summary.json and local-reads.json beside it; MCP reproduction calls 3 and 12 in investigation-accountability/calls.jsonl.

Current owner/source still reproduces the mechanism statically: packages/corpus_recovery/src/corpus_recovery/reconcile.py:161-165 writes the reconciliation string into identity_note while already writing the accepted mapping pin into evidence_sha256. No current-source repair was inferred. The meaningful existing relationship field is kind; a related/substitute recovery is not automatically the original or the only surviving copy worldwide.

Smallest acceptance remains the existing criteria: keep provenance in its named evidence field, emit a human relationship explanation or NULL in identity_note, and verify no reconciliation boilerplate on a fixed recovery fixture. Then qualify and publish a release and read the installed get_document recovery section back; a local producer change alone does not fix selected e4538f00. Preserve status open.

**2026-11-04T15:23:03Z**

Coordinated producer plan frozen 2026-11-04: docs/plans/congress-explorer-root-cause-remediation-20261104.md. This addendum refines remaining work without rewriting prior evidence. Live evidence remains release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; source inspected at 730a2d8e0c55880fc058d13cc74d265fc315f41f. Planning/ticket update only: no implementation, tests, prepare, acquisition, data changes or publication.

Owner: recovery decision authoring/reconciliation, where reconcile.py:161-165 writes evidence_sha256 and wrongly repeats provenance into identity_note. Future authoring emits a supported explanatory note or NULL. For historical bad notes, verify the existing append/supersede command and decision-identity policy before writing corrections: retain old immutable decision bytes and evidence, do not overwrite the same ID with changed content. The exact generated sentinel cohort can receive metadata corrections; do not manufacture explanations for unknown relationships. A persistent downstream stripper with the producer bug intact is not cause removal.

Add an exact-sentinel fixture and a genuine explanatory note/NULL control to maintained owning/native tests. Preserve recovery occurrence count, kind, bodies, URLs, sizes, attachment and accepted-map provenance. The known recovery-backed subset is 6,546 documents / 7,314 occurrences (7,127 pipeline notes, 187 NULL), not a new release-wide denominator. DATA-MODEL section7.8 owns latest remaining decisions and occurrence attachment.

This repair needs metadata interpretation/correction only: no body fetch, rehash, decompression or captures/readings replay. Correction command/identity proof is a hard prerequisite; count/bytes of authoritative corrections remain unmeasured. Work is otherwise parallel with witness/nomination/recording repairs. After qualified producer/native output, use existing gates and verify the delivered get_document recovery field on the actually selected release; keep local versus published states distinct.
