---
id: ct-f6hr
status: in_progress
deps: [ct-55qo]
links: [ct-cbkz, ct-en4n]
created: 2026-11-13T17:46:16Z
type: bug
priority: 1
assignee: mikewolfd
tags: [body_text, html, xml, spicy-docs, compatibility]
---
# Handle retained HTML encoding and XML compatibility failures under explicit policies

The retained recovery checkpoint contains 231 HTML UTF-8-only refusals, 284 XML DOCTYPE-policy refusals and one markup max_events refusal. The latter is now identified as a valid House floor Atom feed; ct-en4n owns its feed role and routing. Reviewed specimens establish Windows-1252 HTML and an empty internal XML subset as recoverable compatibility cases. Confirm remaining members before generalizing. One malformed-XML refusal stays separate. Existing ct-cbkz / upstream ss-mkxe cover text normalization, not these encoding, XML policy or resource acceptance gaps.

## Design

Spicy-docs owns explicit decoding, safe XML parsing and bounded/streaming markup consumption; CT owns declared reading policies, measured worker admission and selective CPU-only rereads. Reuse maintained readers and verify current shared-reader work before implementing overlapping fixes. Record the selected encoding and original byte identity; do not silently insert replacement characters. Permit qualified empty subsets without entity expansion or external resource loading. The event-limit specimen is a complete Atom feed with escaped HTML, not a damaged legislative document. Reuse entry-level feed parsing through a qualified shared adapter before proposing any generic markup limit increase. Keep unrelated PDF output unchanged by this markup change.

## Acceptance Criteria

1. Read the retained legacy-encoding, empty-subset and max_events specimens through the actual CT consumer, preserving source-confirmed text. Report exact affected predicates and unreviewed members.
2. Cover conflicting/missing encoding declarations, UTF-8, preformatted HTML, empty subsets, entity declarations, malformed/truncated XML and large valid input. Prove no external XML fetch or entity expansion; preserve original byte locations where the API exposes them.
3. Preserve the measured event-limit finding and route the valid Atom-feed case through ct-en4n. Measure actual compatibility specimens under worker supervision; malformed/unsupported inputs remain explicit refusals.
4. Integrate with ct-cbkz without conflating normalization and compatibility. Declare versions, reread affected CPU markup cohorts and reconcile current selection, active refusals and historical evidence.


## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.

**2026-11-13T18:48:44Z**

Upstream normalization exists, but the audited reader still enforces UTF-8 and rejects internal XML subsets. The retained max_events example is 38.9 MB and appears cut off; do not call it a proven memory failure or rewrite streaming without a source-completeness check and measurement. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T19:48:19Z**

Correction to the tentative truncation finding: c90e782a00651261a9ac21ae8d30df88757b3b66ae99a5ff794f0dc8ca65336e is a complete, well-formed 38,854,265-byte Atom feed from https://docs.house.gov/BillsThisWeek-RSS.xml (retained HTTP 200, complete=true). It contains 2,226 entries, 15,590 elements and 4,721,751 Expat text callbacks, largely from escaped HTML. Current CT refuses at max_events after 1.25 s / 0.26 GiB peak RSS. A temporary in-process six-million-event measurement completed in 7.03 s / 1.34 GiB RSS, yielding 29,888,608 text bytes. No production limit changed. This belongs to feed-role/routing under ct-en4n; it is not a truncation or out-of-memory verdict. Exact archived original, input pin and measurements: repairs/ct-f6hr-event-limit-20261113/ under the durable OCR recovery root. Encoding/empty-subset work remains open. No publisher refetch or OCR ran.

**2026-11-13T21:30:08Z**

Implemented shared compatibility and a separate retained-XML recovery inspection path; acceptance remains open.

Shared commits, based on CT-qualified ce38a3db: d2ad8df3cf2e069ec218e83ae0a46cca85e4c5d7 (explicit HTML decoding and empty XML subsets), 1712fa199a878bb7d41c92e4fdab8d4704ae3cd5 (bounded partial XML recovery candidates), b064f96aa8d5b0d93dcd2cb10237b1063af64b94 (qualified amendment routing and indentation punctuation). CT operator commit: 697132ee9aa01878f9d6c2a4518d498c59a573c2. Final wheel/version composition belongs to the integration owner; this work changed no CT package pins.

Exact retained originals a8b5d817aa436ffdadafec57b1b2f61d1dce2a9af335a9d47eb4488ca737c1d5 (undeclared Windows-1252 HTML) and 289eef3d0a85ae8fd610f49c70642d0d36502a5089bfa19cb88717ae39f9d3e3 (UTF-8 BOM plus empty DOCTYPE subset) now complete. Original byte positions remain valid; the cleanup record states HTML source_encoding/encoding_basis. Conflicting/unsupported encoding declarations, undecodable bytes, entity declarations, external-resource expansion, nonempty internal subsets and malformed XML remain explicit strict-reader refusals. Generic event limits were not lifted; the complete House Atom source remains ct-en4n's feed route.

The malformed resolution 4cad751b9ec4c7584d60e1d5059b70d29672853056fd789766b9decad7092498 was investigated and a repair attempted. Direct raw reading establishes that it ends mid-idref attribute after TITLE II in its table of contents. Maintained lxml recovery closes the open elements and drops that unfinished attribute. The CT offline command produces candidate 59e0ad5cad7682e8a69667ce74fadae8660840ab85328411ce674eace459d94f and text 1b134876c4e9a8e624ba9c9697b2c61e101655cdc6900d770dc70ce59eb7d1eb, explicitly partial/not_qualified_for_selection. Candidate coordinates never claim original-byte positions. Missing legislation remains unavailable; no inference or OCR can establish its absent bytes.

Evidence root: /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ocr-recovery-20261113/repairs/ct-markup-compatibility-20261113. Direct-review chains, input/intermediate/output paths and hashes are in data-review-final/manifest.json. Actual CT operator artifacts are ct-operator-final/{original.raw,repair.json,candidate.xml,candidate.events.jsonl,candidate.txt,output.json}. The prior data-review packet is retained to show the metadata/inline-spacing issue and its correction. The independent named reviewer is the coordinating agent; its final review must be attached before acceptance, rather than treating tests as data review.

Validation: 288 shared focused tests passed (two deselections: existing live test and root-owned derivation pin reconciliation), Ruff and diff checks passed; CT production-offline focused operator file passed six tests, explicitly a partial lane. Ten real CT consumer inputs produced nine completed readings and one preserved malformed-source error; native PDF control text stayed identical and no OCR ran. Private CT probe used lxml 6.0.2/libxml2 2.14.6; shared helper tests used lxml 6.1.3 with the same libxml2.

Remaining gates: final composed CT package/declarations and decoding-evidence propagation; direct review of that final consumer output; qualify the unreviewed members of the encoding/DOCTYPE cohorts before selective CPU adoption; retain the truncated-resolution missing-source gap. OCR stays paused, refetch deferred, historical readings/refusals and production selection unchanged.

**2026-11-13T21:33:15Z**

Independent direct data review completed by /root/ocr_ticket_completion on the final bounded shared and actual CT chains. Signed review: /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ocr-recovery-20261113/repairs/ct-markup-compatibility-20261113/data-review-final/independent-content-review.md. It confirms the unchanged original-byte evidence, corrected qualified amendment/bill output, actual CT Windows-1252 result, and separate partial recovery without invented missing legislation. This supersedes the earlier pending-review note for these specimens; final composed-package, unreviewed-cohort and production-selection gates remain open.

**2026-11-13T21:54:18Z**

Durable shared-helper follow-up; keep the current qualified CT wheel/pin stable.

The shared public helper `spicy_docs.reading.xml_recovery.recover_xml_candidate` has a committed follow-up at **8fc2fbcdd4bcb32a06dcc1f0d2dc01882a9d8856**, branch **codex/ct-markup-compatibility-20261113**, in the SpicyDocs repository. Its worktree is `/Users/mikewolfd/Work/worktrees/spicy-docs-ct-markup-compatibility-20261113`. The fix applies `max_candidate_bytes` to unchanged valid originals as well as rewritten candidates. A bound one byte below the original now refuses; an exact-size bound still returns the original unchanged. Shared focused recovery checks: 27 passed. Root owns pushing and later packaging this source commit; this note does not claim it is present in the current CT wheel.

CT already has the independent operator guard in **aa4c1a45e177d502679d52977d300aabde553e27**. It enforces the returned-candidate cap before writing or rereading, preserves the shared helper observation and explicit final operator refusal, and retains final output records for expected input/consumer refusals. Ten focused CT checks passed with the pre-8fc2 shared wheel; therefore the shared follow-up is not a prerequisite for the current CT operator correction and does not require reopening the qualified wheel/pin. The actual 26-byte input with an 8-byte candidate cap now exits two and retains original/repair/output records without writing an oversized candidate. Evidence: `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ocr-recovery-20261113/repairs/ct-markup-compatibility-20261113/mechanism-review-bounds/`, particularly `candidate-bound-fixed/output.json` and `ct-bound-tests-final.log`.

Related shared tracking is [ss-mkxe](/Users/mikewolfd/Work/spicy-stack/.tickets/ss-mkxe.md). Its existing note assigns compatibility and XML-policy work to ct-f6hr, so this follow-up stays here instead of creating a duplicate ticket or widening the normalization ticket. Later SpicyDocs packaging should include or explicitly account for 8fc2fbcdd4bcb32a06dcc1f0d2dc01882a9d8856. Ordinary reading behavior, OCR pause, deferred refetch, production selection and publication are unchanged by this note.
