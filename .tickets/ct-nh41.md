---
id: ct-nh41
status: open
deps: []
links: [ct-zkzt, ct-rie2]
created: 2026-11-04T02:45:03Z
type: bug
priority: 3
assignee: mikewolfd
tags: [publication, recoveries, mcp, chaos-test]
---

# Record what a recovered document is evidence of

Give archive and Congress MCP users a supported explanation of a recovery's relationship to the original, or no explanation when that relationship is unknown. Release `e145d24c389e` removed generated boilerplate from 10,772 notes; all 12,618 current recovery occurrences now have null `identity_note`. The public symptom is mitigated, while the producer still authors the misleading field.

## Root cause (2026-11-05)

`packages/corpus_recovery/src/corpus_recovery/reconcile.py:161-165` writes `Reconciled from pinned accepted mappings ...; receipt categories preserved` into `identity_note`, duplicating provenance already held in `evidence_sha256`. `model/sql/provenance-remaining-recovery-decisions.sql` strips that exact generated sentence. The reconciler owns cause removal; the compatibility filter remains necessary while supported historical inputs contain the sentinel. The campaign import reason `source_identifiers_match` is a rule result, not a detailed human explanation. Neither a hash nor successful reconciliation proves the recovered document's semantic relationship.

## Acceptance Criteria

- Future reconciliation emits an evidence-supported relationship explanation or null in `identity_note`; it never generates the provenance sentinel. Keep the reconciliation pin in `evidence_sha256` and preserve the recorded relationship `kind`. Do not fabricate explanations or promote an acceptance reason into additional identity evidence.
- Exercise the actual producer on fixed accepted mappings with an explanatory note, unknown relationship/null and legacy sentinel. Verify new output no longer authors the sentinel, genuine supported notes survive, and legacy publication still filters only the exact generated sentence. A passing output filter alone does not demonstrate producer repair.
- Preserve immutable legacy decisions and their evidence. If a historical correction is needed, first verify the maintained append/supersede identity rule and retain old bytes; never overwrite an existing decision ID with changed content. Preserve recovery counts, kinds, bodies, URLs, sizes and attachment for this metadata-only change.
- Verify schema and `get_document` wording accurately describe an explanation or null. Use the maintained release gates, then read the selected release through MCP and the site: no generated sentinel, supported notes visible and unknown relationships still null. Retire any site special case only when all supported release behavior permits it.
- Reuse retained metadata and fixtures. No new body fetch, decompression, filename reparse or capture replay is required. Record source-local, candidate and delivered evidence separately.

## Evidence

[November 5 root-cause analysis](../docs/experiments/url-normalization-revalidation-20261105/root-causes.md); `.cache/archive-release/investigations/url-root-cause-20261105/etl-recovery-campaign/report.md`; current release queries in `.cache/archive-release/investigations/url-revalidation-20261105/`. Older notes below retain their original release and population boundaries. Campaign progress/publication-gain reporting is owned by [ct-rie2](ct-rie2.md); this ticket changes explanation authoring.

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
