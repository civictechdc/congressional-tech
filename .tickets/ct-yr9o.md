---
id: ct-yr9o
status: closed
deps: []
links: [ct-717p]
created: 2026-11-02T18:20:46Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [records, post-release]
---

# Record malformed House XML as unreadable

A corrupt House XML body should leave a failure that operators can find. Meeting, appearance and committee record builders currently turn XML parse failures into completed empty results. The retained v21 audit found zero affected bodies: all 6,179 House XML meeting rows held a meeting, and witness lists for `111420` and `105459` were valid empty lists. That historical result does not establish the current affected population.

## Smallest useful change

Defer this to a later intentional House record transition that explicitly supports changed failure dispositions. Let malformed XML reach the shared `unreadable_decision()` path. The newly merged document-reference backfill requires completed rows and unchanged values and refuses pending unreadable decisions, so its equivalence proof cannot qualify this change. The Rules intake gap remains with `ct-717p`.

## Acceptance Criteria

- All three House XML record builders surface malformed syntax to the shared decision writer. The existing strict expected failures in `test_record_producer_unreadable.py` become passing cases. Exercise those malformed inputs through the maintained staging path and its decision consumer, not only the builder.
- Preserve valid empty lists and well-formed wrong-root inputs as completed empty results. State blank-input behavior at admission and keep missing body bytes pending. Record one durable failure decision per affected body, parser and version; a rerun at the same selected version must not retry a settled failure.
- Before widening any replay, inspect selected XML/error candidates and name the affected scope. Record the intentional source-scoped pin change and accepted unreadable outcomes. Reuse qualified unchanged values and retain the historical valid-empty evidence.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).


## Notes

**2026-11-05T20:56:46Z**

Final root-cause review: keep malformed-XML handling for a source-scoped transition that accepts unreadable decisions. The completed-only document-reference backfill does not qualify this change.

**2026-11-06T17:21:30Z**

Isolated implementation is ready on `codex/ct-yr9o-house-xml-20261106` (base `742dbe70`). All three House builders now send irreparable syntax errors through the maintained unreadable writer. User follow-up also requested a normalized repair path: one opt-in strict-first helper escapes clearly literal ampersands in text/quoted attributes, returns rule/count plus original/normalized hashes, and accepts only a complete strict parse. Raw bodies remain unchanged. Unknown entities, DTD repair, encoding guesses and truncation are refused. General readings and MODS keep their strict behavior.

The three House version pins intentionally move; non-House versions match the base, and publish.json binds the updated model specification. Generic reading diagnostics match the base exactly with the pinned tools; existing sniff/bundle warnings predate this change. Declared reading versions and compatibility entries remain unchanged.

Focused production-offline verification passed: 53 cases, partial selection of 4 lane files, not a full-lane result. Cases include real builders on malformed inputs, selected XML-error routing, supported repair, one durable decision per body/parser/pin despite duplicate captures, a fresh-engine same-pin rerun with no work, wrong-root/blank/valid-empty controls and missing bytes remaining pending until arrival. Watchdog peak: 0.34 GiB RSS. Original bodies for witness lists 105459 and 111420 preserve their selected empty fields.

Pattern inspection found two XML errors in the retained readings import source, both truncated House resolutions (4cad751b9ec4 and 9da6a0c457ee), with saved bytes matching their recorded hashes. One ends inside an attribute; the other ends mid-sentence. These need complete source bytes, not invented closing tags. They are not meeting/witness lists and do not establish current affected counts or corpus repair gains. See docs/house-xml-normalization.md and main .cache/archive-release/implementation/reviewed-non-news-20261106/ct-yr9o/.

Ticket remains open for the release owner's frozen-candidate scope inspection and source-scoped transition accepting changed unreadable/repair outcomes, qualifying carried-forward values and reconciling selected table/decision inputs. The completed-only document-reference backfill does not qualify this transition. No corpus replay, broad acquisition, shared import, model build, main merge, push or publication occurred.

**2026-11-06T18:04:23Z**

User-authorized follow-up refetched only the two exact truncated-source URLs. Both returned HTTP 200 and complete XML with no normalization: `4cad751b9ec4...` (3,289 bytes) is an exact prefix of new body `aa7fc97adeb1...` (225,788 bytes); `9da6a0c457ee...` (3,411 bytes) is an exact prefix of new body `0d9fd999da81...` (96,044 bytes). ElementTree and the maintained strict XML reader accept both complete responses. This points to earlier capture/import truncation; its precise source is not established.

The maintained Fetcher, DirectAdapter, host pacing, ReceiptWriter and local create-only BodyStore retained both new bodies and receipts under main `.cache/archive-release/implementation/reviewed-non-news-20261106/ct-yr9o/refetch/ct-yr9o-refetch-20261106T180233454667Z/`. `qualification.json` binds exact new body keys, original hashes and receipts. Original shared raw objects remain unchanged. These two authorized requests supersede the earlier implementation-phase statement of no source acquisition. No shared raw/catalog import, corpus replay or publication occurred. Release/recovery integration still owns importing these local inputs with their receipts and reconciling affected selections; ticket remains open.

**2026-11-06T18:43:10Z**

Implemented and locally qualified malformed House XML handling at 5b0463d2, with safe shared normalization, preserved empty/missing-byte behavior and durable same-version retry suppression; 53 focused production-offline cases passed (partial lane). Follow-up fdb62438 records two successful exact-URL refetches: both complete XML bodies and receipts are retained locally, with the old fragments preserved. The scoped transition proposal now binds the settled eight-selector/24,341-receipt inputs and producer history, defines reuse and failure/pending conservation, and names 585 ambiguous anchor pairs plus resource limits; its read-only measurement peaked at 0.51 GiB RSS. Evidence: reviewed-non-news-20261106/ct-yr9o/transition-plan/PLAN.md. Independent four-skill review is running against the unchanged source commit.

Remain open: original root owns admission/assignment of the exact-selected-input census, registered transition caller and bounded producer/recovery imports; ct-m104 owns the resulting final native/model and selected-release/publication checks. No retained transition, shared import or live delivery is claimed.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at 5b0463d2. The reviewed House XML repair preserves valid-empty results, missing-byte pending work and settled-failure retries. The admitted metadata-only census completed on 11,795 current candidate pairs and exposed 4,027 previously selected pairs excluded by current discovery. The corrected proposal preserves all 15,822 selected pairs. Existing exact-URL captures, XML results and strict-parse evidence for both refetches reduce inspection to 583 pairs; no new imports are required merely for their availability. Discovery cannot authorize deletion.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Reviewed isolated transition caller and preservation controls, separately admitted parsing/import phases, then final native/model and selected public acceptance. The original capture/import truncation mechanism remains unresolved. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-yr9o/REVIEW.md).

**2026-11-06T20:26:32Z**

Integrated the independently approved local transition caller aa1f7d0f into main at 07c10cba. The bounded pilot and complete local cohort passed at that combined source: 15,822 selected keys and all semantic values are preserved, excluding only the intentional parser_version change. This includes all 4,027 pairs outside current fetch eligibility. Reused 15,237 pairs and recomputed 585 pairs across 584 bodies; zero new unreadable decisions and zero pending work. Peak cohort RSS was 0.636 GiB. The 31 baseline decision files remain unchanged, and a fresh native runtime found no remaining work.

Both complete refetch bodies already exist in the frozen inputs, so no new imports are needed. The two truncated fragments were outside this transition and were not replayed. Shared table activation is still under focused implementation/review; final native/model, document-download selection and selected public acceptance remain open. No shared tables or publication changed during the local cohort. Evidence: .cache/archive-release/implementation/merge-prune-20261106T180951Z/house-transition-cohort-handoff-review.md and house-transition-cohort-retained-checks.json.

**2026-11-06T21:15:10Z**

Closed after the reviewed implementation and real shared House transition completed in main at 0debd552. Independent native readback confirms all 15,822 selected records match the accepted stage exactly, including 4,027 outside current fetch eligibility: no missing or extra keys, duplicates or changed values. The three new-version table heads have valid daily history; all five other selectors, the receipt inventory and 31 unreadable-input files remain unchanged. No new unreadable decisions or pending work were produced.

Malformed, valid-empty, wrong-root, missing-byte and settled-failure behavior is covered by the maintained native-consumer fixtures; the real selected cohort completed successfully. The accepted fresh-native zero-work evidence transfers through exact row and input equality. No full daily run or deployment is claimed. The two recovered-document download checks and final release qualification remain with ct-m104.

[Independent acceptance](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/house-transition-activation-acceptance.md) and [actual execution](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/house-activation-execution-attempt02.json). The first pre-write credential-environment failure remains retained; the successful run peaked at 0.476 GiB RSS. Scope: this ticket's three acceptance criteria are complete; broader publication and operations remain separate.
