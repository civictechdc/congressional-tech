---
id: ct-f6hr
status: in_progress
deps: [ct-55qo]
links: [ct-cbkz, ct-en4n, ct-fb7k, ct-n3ik]
created: 2026-11-13T17:46:16Z
type: bug
priority: 1
assignee: mikewolfd
tags: [body_text, html, xml, spicy-docs, compatibility]
---
# Handle retained HTML encoding and XML compatibility failures under explicit policies

Legacy encoding and empty-subset support are merged, and the complete House Atom feed uses its dedicated reader. The full markup reparse leaves 35 directly reviewed refusals: six useful historical readings, seventeen useful recovery candidates, eight error responses and four damaged sources. The seventeen candidates now have real separate-version readings and text in a private native catalog, preserving every ordinary error row. CT PR168 now has the import-layer correction at 8c1a317b and 114 focused passing checks; updated CI, accepted selection and publication remain.

## Design

Spicy-docs owns explicit decoding, safe XML parsing and bounded/streaming markup consumption; CT owns declared reading policies, measured worker admission and selective CPU-only rereads. Reuse maintained readers and verify current shared-reader work before implementing overlapping fixes. Record the selected encoding and original byte identity; do not silently insert replacement characters. Permit qualified empty subsets without entity expansion or external resource loading. The event-limit specimen is a complete Atom feed with escaped HTML, not a damaged legislative document. Reuse entry-level feed parsing through a qualified shared adapter before proposing any generic markup limit increase. Keep unrelated PDF output unchanged by this markup change.

## Residual failures from the current CPU reparse

Legacy encoding and empty-subset support are merged, and the large feed has a dedicated route. The completed run has 35 refusals, all directly reviewed: six useful historical transcript readings to preserve at their actual old keys, seventeen useful private encoding/literal-entity candidates, eight error responses and four damaged/truncated sources. Exact actions and the final nine-case review are frozen under repairs/markup-reparse-20261114/residual-diagnosis-final-tail-20261114/. The seventeen candidates now have declared recovery policies and actual private catalog keys; production adoption remains. CT PR168 preserves seventeen old errors beside seventeen new readings and text rows, and corrected its import-layer placement at 8c1a317b before updated CI acceptance. The opt-in shared helper merged in spicy-docs PR30 at e934cfb1c99532a542b946eaa884c4b87196a729 after CI. Default CT reader behavior and the running bulk wheel remain unchanged.

Group final refusals by demonstrated cause and inspect representative original bytes and actual intermediate diagnostics. Reuse maintained spicy-docs decoding/XML recovery capabilities where they preserve useful text. Do not add permissive replacement decoding, external entity loading or silent partial-success labels. Preserve damaged/ambiguous sources explicitly. Qualify a versioned fix and retry only matching failed keys in a separate lane; do not mutate the running bulk policy or reparse successful unrelated bodies. ct-n3ik records impact and remaining remedy, ct-cbkz adopts accepted results.

## Acceptance Criteria

1. Read the retained legacy-encoding, empty-subset and max_events specimens through the actual CT consumer, preserving source-confirmed text. Report exact affected predicates and unreviewed members.
2. Cover conflicting/missing encoding declarations, UTF-8, preformatted HTML, empty subsets, entity declarations, malformed/truncated XML and large valid input. Prove no external XML fetch or implicit parser entity expansion. Any explicit literal-entity candidate must retain original/candidate hashes and exact bounded edits, refuse external/parameter/recursive entities, and remain unqualified until actual-key review. Preserve original byte locations where the API exposes them.
3. Preserve the measured event-limit finding and route the valid Atom-feed case through ct-en4n. Measure actual compatibility specimens under worker supervision; malformed/unsupported inputs remain explicit refusals.
4. Integrate with ct-cbkz without conflating normalization and compatibility. Declare versions, reread affected CPU markup cohorts and reconcile current selection, active refusals and historical evidence.
5. Reconcile every residual error to a demonstrated safe repair, deliberate policy refusal or named unresolved cause. A named reviewer directly reads raw bytes -> actual parse/repair intermediate -> final output for representative causes and controls; retries do not count as success without usable retained text and exact identities.

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

**2026-11-13T22:24:49Z**

Qualified an additional retained native compatibility case at substantially larger size through the current composed CT consumer: SHA `abfd84a3bd8c52efa3c519060f04385b21c231117a77e350dc0492eccbf7db08`, Rules Committee Print 117–21 / House amendment to S. 1605, 8,325,960 original bytes. Its exact original has a UTF-8 BOM, the native amendment v2.8 DTD, an empty internal subset and `amendment-doc` root. Current CT 0e74c264 with shared 0.85.0+ctreaders.20261113.2 completed 397,364 events in 0.8924 s, with no original repair, entity/resource loading or generic event-bound increase. Text SHA is `db83ee945ebd13ccb5cf786bb043914c28c852fe25dd7a89befe63f460fa4f60`.

The coordinating agent independently read original, actual shared events and CT output for the opening, first Army table and tail. Narrow administrative metadata removal, draft facts, inline short-title period, sampled installation amounts and final 90-day effective date match the source. Qualification is limited to those passages; empty table-cell structure and unread sections are not certified. Exact paths, hashes, version/reader pins and measured resource limits are under `repairs/ct-markup-compatibility-20261113/capacity-reachability/`, especially `independent-data-review.md`.

This supplies another real member of the safe-empty-subset predicate. It does not qualify every encoding/DOCTYPE refusal, full reading adoption, current remote custody or missing source bytes. The 400 missing capture storage pins still have `copy_usable=false` despite retained size observations; do not silently admit them. Existing shared helper follow-up `8fc2fbcdd4bcb32a06dcc1f0d2dc01882a9d8856` remains separate from this unchanged qualified wheel. OCR stays paused and publisher refetch deferred.

**2026-11-13T22:28:34Z**

Durable shared-helper follow-up; keep the current qualified CT wheel/pin stable.

The shared public helper `spicy_docs.reading.xml_recovery.recover_xml_candidate` has a committed follow-up at **8fc2fbcdd4bcb32a06dcc1f0d2dc01882a9d8856**, branch **codex/ct-markup-compatibility-20261113**, in the SpicyDocs repository. Its worktree is `/Users/mikewolfd/Work/worktrees/spicy-docs-ct-markup-compatibility-20261113`. The fix applies `max_candidate_bytes` to unchanged valid originals as well as rewritten candidates. A bound one byte below the original now refuses; an exact-size bound still returns the original unchanged. Shared focused recovery checks: 27 passed. Root pushed this source branch; later packaging remains separate; this note does not claim it is present in the current CT wheel.

CT already has the independent operator guard in **aa4c1a45e177d502679d52977d300aabde553e27**. It enforces the returned-candidate cap before writing or rereading, preserves the shared helper observation and explicit final operator refusal, and retains final output records for expected input/consumer refusals. Ten focused CT checks passed with the pre-8fc2 shared wheel; therefore the shared follow-up is not a prerequisite for the current CT operator correction and does not require reopening the qualified wheel/pin. The actual 26-byte input with an 8-byte candidate cap now exits two and retains original/repair/output records without writing an oversized candidate. Evidence: `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ocr-recovery-20261113/repairs/ct-markup-compatibility-20261113/mechanism-review-bounds/`, particularly `candidate-bound-fixed/output.json` and `ct-bound-tests-final.log`.

Related shared tracking is [ss-mkxe](/Users/mikewolfd/Work/spicy-stack/.tickets/ss-mkxe.md). Its existing note assigns compatibility and XML-policy work to ct-f6hr, so this follow-up stays here instead of creating a duplicate ticket or widening the normalization ticket. Later SpicyDocs packaging should include or explicitly account for 8fc2fbcdd4bcb32a06dcc1f0d2dc01882a9d8856. Ordinary reading behavior, OCR pause, deferred refetch, production selection and publication are unchanged by this note.

**2026-11-13T23:17:11Z**

The retained 8,325,960-byte amendment abfd84a3bd8c52efa3c519060f04385b21c231117a77e350dc0492eccbf7db08 also passed through the real current CT worker and native Parquet staging path. The original UTF-8 BOM, native amendment DTD and empty internal subset use the existing explicit compatibility policy; no source rewrite or limit increase was needed. Final text remains db83ee945ebd13ccb5cf786bb043914c28c852fe25dd7a89befe63f460fa4f60, identical to the already directly reviewed candidate.

The named intermediate/final review and exact runtime/custody limitations are in repairs/ct-markup-compatibility-20261113/role-partition/producer-probe/direct-data-review.md and README.md. This closes the bounded producer-stage evidence gap for that identity only. Remaining encoding/DOCTYPE cohort qualification, missing truncated-resolution bytes and selected-output adoption stay open. Shared helper integration is tracked in https://github.com/mikewolfd/spicy-docs/pull/27; current CT qualified wheel and ordinary XML defaults remain unchanged. OCR remains paused and publisher refetch deferred.

**2026-11-14T05:39:37Z**

Shared feed/XML changes are merged in spicy-docs PR27 (merge f9584d8bbc6d14c7707fbf53d3487e024b0455b8), with full CI passing at 3c5e962b7658c88f088a5f7a33f12e979977903a. The final leaf-schema/reader typing correction preserves the reviewed feed and malformed-XML candidate bytes: 1 feed / 2,226 entries / 65,511 link occurrences, plus the identical partial XML text and 88 ordered events. Exact replay/equivalence evidence: repairs/shared-feed-upstream-20261113/pr27-ci-correction/.

The maintained explicit recovery path bounds candidate bytes and retains source hashes, diagnostics and partial/refusal outcomes. It cannot reconstruct missing source bytes. CT's qualified wheel remains 0.85.0+ctreaders.20261113.2; no current-version restamping, corpus reparse, selection, OCR or refetch followed from the source merge. Cohort role/custody qualification and selected-output adoption remain open.

**2026-11-14T06:07:10Z**

The maintained current CT planner now nominates the already directly reviewed empty-DTD amendment abfd84… at xml_text version 5a0768…798c from six authentic capture observations and its frozen compatible sniff row. Both previously reviewed larger HTML inputs are also nominated at html_text version f1cefe44…94a3 after the authoritative capture lookup preserved all 60 source observation identities. No historical version was restamped, null field invented, duplicate capture collapsed, body worker started or production reading selected. Exact planning evidence: coordination/markup-current-plan-eligibility-20261114/ and coordination/markup-current-plan-html-eligibility-20261114/. Source-copy custody and broader cohort adoption remain separate acceptance gates.

**2026-11-14T12:31:10Z**

Scoped the next diagnosis to the final residual-error manifest from the unchanged HTML/XML run. Representative known causes are declared Windows-1252 failures, conflicting declarations and XML entity-policy refusals. Confirm causes from original bytes, use qualified shared-reader repairs, and retry only affected keys in a separate lane. Preserve ambiguous/damaged sources and historical refusals. No permissive decoding or policy change was applied.

**2026-11-14T14:33:16Z**

Shared opt-in encoding/literal-entity recovery merged after CI in spicy-docs PR30: https://github.com/mikewolfd/spicy-docs/pull/30, merge e934cfb1c99532a542b946eaa884c4b87196a729. Root independently read full H.R.3706 raw/candidate/actual CT output and the advisory declaration/body/output chain, reproduced both candidates through the unchanged actual CT consumer, checked refusal controls and caught planted missing passages. Shared tests passed; initial full CI found only a missing docs-index link, repaired at 503e12b6. No default-reader or CT wheel change.

Through batch476, 26 refusals are directly reconciled: five useful prior transcripts retain their actual old html_text key; twelve encoding/literal-entity candidates have useful private CT outputs; six are source-error responses; three are damaged/truncated. Exact actions/reviews are in repairs/markup-reparse-20261114/{residual-diagnosis-20261114,residual-diagnosis-batch476-20261114}/. Candidates are not committed lake readings or accepted selections. Tail cases beyond this cutoff still require diagnosis; only exact failed predicates may be retried. OCR remains paused and publisher refetch deferred.

**2026-11-14T15:08:53Z**

Final nine residuals were directly read by /root/shared_reader_ci_finish through raw source, actual repair/parse intermediate and complete candidate output. Combined all35: 6 useful actual older readings, 17 useful private candidates, 8 error responses and 4 damaged sources. Final-tail source-review.md SHA 037634468b877343901b39404fa6e4f911b065e13899f786ad6d424eb014d57a; exact new actions SHA de32d3baf8cecbbed79c5dd7e6f5d4cee4106eb42e725ccd8a005c0e3cb51250 under repairs/markup-reparse-20261114/residual-diagnosis-final-tail-20261114/. Shared PR30 is merged; the agent now owns maintained CT recovery integration and actual-key qualification for the17 candidates in a separate lane. Candidates are not yet selected production readings.

**2026-11-14T15:57:37Z**

Private actual recovery integration qualified 17 originals / 667,347 source bytes to 17 separate-version completed readings plus 17 text rows / 316,630 text bytes, retaining 17 ordinary errors unchanged; repeat append is a no-op. Source 091b0190, PR #168; helper SpicyDocs PR #30, wheel 0.85.0+ctrecovery.20261114 SHA d54c1723… retains all 602 pre-existing members. Root independently approved exact inputs/actual keys and replayed real HTML/XML plus wrong-source/helper refusals; report SHA 3672f872147ae19807fa5c9f43368ea42232adce79808da31454df45402442e3. CI then caught parser-to-lake import fencing; author is relocating the coordination operator byte-identically into lake before rerunning affected checks. No selection/publication yet. Evidence: repairs/markup-reparse-20261114/ct-recovery-integration-20261114/.

**2026-11-14T16:03:03Z**

PR168 correction pushed at 8c1a317b04b01862d8ca9f604266246d36f1d250: recovery coordinator moved byte-for-byte into lake, callers and diagnostic location updated, import fence unchanged. All 114 focused checks passed. Root independently verified Git-object identities, unchanged ordinary declarations/fixtures/tools/policies, and the limited workspace fingerprint delta. Root review SHA 5a5bb7ad03f6e876632f47e8585a1db37870cbf1291b4bf26b5f2cab068fd52c. Original 17-body evidence remains valid by exact extraction/helper/wheel identity; updated CI must pass before merge.
