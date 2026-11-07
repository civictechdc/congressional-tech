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

**2026-11-06T17:21:15Z**

Isolated producer repair and local metadata-correction preparation completed on codex/ct-nh41-identity-notes-20261106, based on 742dbe70b42f0618e95816cd7cf0e6ba2f9939b0. Reconciliation now preserves explicit pinned mapping explanations or emits null; it no longer generates the provenance sentinel. Campaign requests accept explicit explanations or null and no longer promote source_identifiers_match into identity evidence. The authored-or-null-v1 policy participates in new decision IDs/operation bindings so changed content cannot reuse the legacy identity; existing legacy stages stay immutable.

Added correct_generated_note for metadata-only preparation: it accepts only the exact sentence containing that decision's own evidence pin, returns a new ID with supersedes=old ID, and preserves body/URL/kind/evidence fields (including version-2 acceptance fields). The maintained congress_api.cli.provenance command created and inspected a local eight-decision correction stage; no --apply to shared state occurred. Native selection over the two pinned e145 recovery inputs (24,085 historical decisions) remained 24,028 current decisions before and after the eight supersessions. The original input bytes, selected original records, source pins and stage remain in .cache/archive-release/implementation/reviewed-non-news-20261106/ct-nh41/metadata-proof/. This is a bounded correction proof, not a release-wide correction mandate or a new recovery/document gain.

Reused ct-umtm's real one-target USAID/ecoi.net cohort. metadata-proof/cohort-identity-note.json supplies an authored request fragment backed by the pinned catalog record and retained cover text, attributing the shared title/date and explicitly leaving historical byte identity unestablished. It is not an import request or acceptance decision. Candidate receipt and truthful native-catalog match-basis handling remain with ct-rie2/shared integration; per-target adjudication remains with ct-umtm.

Verification: own uv sync --frozen; own pinned local runtime; retained Poppler 26.06.0; watchdog-protected scripts/dev.py test production-offline on five focused files (test_identity_notes, test_engine_recovery_import, test_campaign, test_phase1_provenance_model, test_provenance_contract), partial exit 0. Peak RSS 0.511 GiB; metadata proof 0.143 GiB. Actual reconciliation, explicit-note/null/legacy controls, campaign restart identity, version-2 preservation, maintained staging/local-only apply retry and native supersession/filter/attachment behavior passed. Initial doctor refusal (default Poppler 26.10.0/import timeout) and an evidence-driver input-shape failure are retained separately. Fixed sniff/readings diagnostic samples matched; no parser/reading extraction semantics or byte-hashed files changed, so existing declared versions remain appropriate for this metadata-only repair.

Ticket stays open for integration and actual selected-release acceptance. Existing exact historical SQL filter, schema and get_document wording, and site compatibility handling were credited and retained. The release owner must decide whether any historical raw corrections are needed, revalidate current decision history before applying a staged supersession, preserve original bytes, use maintained candidate gates and compare counts/kinds/bodies/URLs/sizes/attachment, then verify selected MCP/site explanations and nulls. No body acquisition, body rehash/decompression, parser/capture replay, shared catalog/raw write, full model, release, deployment, scheduler change, merge or push occurred. See docs/recovery/identity-notes.md and durable STATUS.md/HANDOFF.md.

**2026-11-06T18:43:09Z**

Local producer/correction work is complete at 59d0d0631a0cb19adfcf963fdb2bbaedc45b3f53. Reconciliation and campaign imports preserve authored explanations or null; provenance boilerplate and acceptance reasons no longer become explanations. New identities and append/supersede corrections preserve immutable history. All 117 focused checks passed (five-file partial scope). Eight real corrections are staged, unapplied; current decision selections stay 24,028. Source/stage hashes still match; evidence is in .cache/archive-release/implementation/reviewed-non-news-20261106/ct-nh41/{checks.json,COMPLETION-RECHECK.json,metadata-proof/evidence-report.json}. The prepared USAID/ecoi.net explanation remains unchanged in ct-rie2's pending request, and catalog-attribution code is now prepared. No delivery or live change is established.

Keep open: original root 01a1aa05-d4d2-7ca0-b541-a8a52e6c794f owns source integration/shared campaign reconciliation; ct-m104 01a1b1b0-7f7b-7b50-8b00-6f5a05eed772 owns final release gates and selected MCP/site checks for notes, nulls and preserved attachment/fields. Historical raw corrections are optional writer decisions. ct-rie2's actual campaign capture/import is separate; this note repair needs no acquisition or parser replay. No independent producer/correction work remains.

Independent review: REQUEST CHANGES; current owner state: changes requested. These findings remain open until repaired and rechecked. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-nh41/REVIEW-59d0d063.md).

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at 02b84997. Authored relationship explanations or null remain intact. The review found that the site removed authored text beginning with an old boilerplate prefix; cleanup now removes only boilerplate forms. Both regressions failed before repair, then all 37 focused site checks passed. Eight optional metadata corrections remain staged and unapplied.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Shared campaign reconciliation and final selected MCP/site checks of notes, nulls and preserved attachments/fields. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-nh41/REVIEW.md).

**2026-11-07T23:00:34Z**

November 7 closure review credits the completed explanation-authoring repair, deployed consumer behavior, immutable-data parity, and null/legacy controls. The selected release preserves 12,618 recovery occurrences and 11,238 document attachments, with no generated sentinel. The maintained producer has now also accepted the actual USAID/ecoi recovery with its supported authored explanation; operation `21ebd7b7c5c6726d42f4de69ba0065ea3a565b5992eaeafce15fb6f3b27480db` passed remote raw readback and accepted replay.

Keep `ct-nh41` open only for its existing requirement to see a supported non-null explanation in the selected release through both MCP and the site. Public `5d24699ad9fa` still contains zero authored notes. The isolated positive establishes consumer capability; the accepted USAID/ecoi import supplies the concrete public positive for `ct-rie2`/`ct-umtm`'s next coordinated release. Reuse all completed checks. No new acquisition, historical correction, address merging, or separate release is needed. This narrows the owner handoff's original closure recommendation to the one remaining public check. [Owner evidence](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-nh41/STATUS.json) · [Accepted raw result](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-rie2/writer-run/ROOT-RESULT.json) · [Closure review](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/non-mcp-ticket-addendum-02/CLOSURE-REVIEW.md).
