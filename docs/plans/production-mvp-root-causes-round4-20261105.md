# Production MVP root causes: final remaining tickets

This round completes the original 52-ticket review and includes the three tickets added afterward. The remaining News Lake work contains real correctness defects, but belongs to that parked product. It does not become a requirement for sharing the congressional archive. The newly documented wrong bill association is directly relevant to the research product and should join its existing data-quality planning.

Three independent GPT-6.1 Sol/xhigh reviewers applied the greybeard and ETL workflow skills to the seven remaining original tickets and the three additions. They inspected maintained callers, current source, pinned engine source and retained evidence. Recommendations below are audit findings, not implemented fixes or new release gates.

## The seven original tickets

Ranks preserve the original 52-ticket assignment.

| Original rank / ticket | One-line user value | Current state and root problem | Smallest useful end state |
| --- | --- | --- | --- |
| 46 · [ct-tbrj](../../.tickets/ct-tbrj.md) | Know whether a meeting's detail was actually read, and when. | The archive exposes Congress.gov's update time, but not a qualified detail-read observation. Listing and detail records share a source kind. The cited comparison's missing-state note is not a row-level comparison of the upstream attempt journal. | Derive an event-specific detail observation from exact endpoint, receipt and parsing evidence. Keep source update time separate, and represent unavailable evidence as unknown. Confirm the fields needed by the SpicyRegs comparison before publishing them. |
| 47 · [ct-yr9o](../../.tickets/ct-yr9o.md) | Distinguish unreadable House XML from a genuinely empty record. | Three record parsers catch XML failures and return completed empty results. Existing strict expected-failure tests describe this; the measured v21 cohort had no affected body. | At the next intentional House parser change, let malformed input reach the shared unreadable-decision path. Preserve valid empty lists and reuse qualified unchanged readings. |
| 48 · [ct-jo8n](../../.tickets/ct-jo8n.md) | Get the same news answer whenever the same release is requested. | The named-release reader uses exact pins. Downstream derived tables can substitute newer inputs, and incremental history handling assumes forward progress. Retaining a manifest alone also does not protect engine history. | Carry the selected release's exact inputs through derived results, handle older releases explicitly, and protect supported release dependencies through compaction. Reuse the existing reader and native operations. |
| 49 · [ct-4nyy](../../.tickets/ct-4nyy.md) | Export only news content allowed at the requested time. | A versions-only read omits the captures used to decide expiry. Both policy paths can then miss expiry; native timestamp-string comparison adds a separate precision defect. The default CLI reads all tables and masks the subset case. | Resolve policy dependencies from the same pinned release, compare actual instants, and use one qualified native policy. Preserve allowed metadata, explicit authorization, expiry equality and export replay. |
| 50 · [ct-xu1o](../../.tickets/ct-xu1o.md) | Replay a news poll after restart without duplicate or conflicting records. | Time-based lookup falls back to logical ID only for IDs already seen by the process. A first changed-timestamp replay can escape that check; the engine's composite key does not enforce ID-only uniqueness. | Refuse conflicting logical-ID reuse durably before accepting a new physical time key. Make ordinary replay reproduce its record values, then measure the retained pruning approach with equivalent compaction settings. |
| 51 · [ct-d8cf](../../.tickets/ct-d8cf.md) | Recover interrupted news updates while keeping earlier releases usable. | DocSpec CLI routing, native upserts and incremental bridges already exist. Remaining gaps concern writer ownership during commits, rollback state and caches, retained release dependencies, temporal comparisons and runtime selection. | Repair those specific boundaries through the maintained path, port the relevant recovery checks, then retire superseded production code. Keep a test reference where it establishes parity. |
| 52 · [ct-5yof](../../.tickets/ct-5yof.md) | Read the topic and tone labels selected by a news release. | The deterministic keyword producer, typed records and run selector exist. No maintained consumer joins persisted labels to the run selected by the requested release. | Add one reader using the existing run-selection rule, with a persisted two-run case and zero-output replacement. Keep method and taxonomy visible; a new classifier is unnecessary. |

## What the traces establish

### A physical lookup key has become a substitute for logical identity

In [News Lake append lookup](../../packages/news_lake/src/news_lake/storage/docspec/lake.py), `_existing_for_append` first searches the incoming timestamp. It probes missing IDs only when those IDs occur in the process-local `_known_ids` set. A new process has no such history. A changed timestamp can therefore make an existing logical ID look new.

The pinned engine updates on every supplied key column. For a `(time, id)` key, a different time is a different tuple; the engine is not independently enforcing uniqueness of `id`. A retained October 24 probe reproduced the duplicate with an older engine. The current application and pinned engine source still establish the same mechanism; this audit did not rerun it.

The existing test does not cover the decisive cold case. It first replays records in the new instance and then exercises a same-timestamp conflict before the changed-timestamp conflict. Those steps populate the cache. The next check should make the changed-timestamp conflict the first operation in a fresh process.

There is also an upstream trigger to resolve: `build_run` derives the run ID from processor, configuration and inputs, while its timestamps default to the current clock. Reprocessing identical inputs can reproduce the ID without reproducing the record. Retain the distinction between replaying one recorded operation and intentionally creating a new observation. Do not solve a conflicting replay by silently accepting another row.

The existing scale experiments establish selective lookup on synthetic version data. They do not establish whole-poll cost for items, versions and mentions with equivalent compaction. Correct identity first; reuse those measurements as leads for the next bounded comparison.

### Complete release selection must survive every downstream read

[`DocSpecLake.read_release`](../../packages/news_lake/src/news_lake/storage/docspec/lake.py) already checks release availability and reads the manifest's exact table pins. The remaining problem is downstream. `_bridge_pin_for_refresh` can replace a selected bridge with the engine's latest version, and `_base_version` has a similar fallback. The incremental bridge path also consumes after-images and added rows without a general reverse transition for returning to an older release.

The reviewers traced two discriminating scenarios: release A → release B → A, and overlapping derived builds where A selects its inputs before B advances a shared bridge. The source supports a risk of a wrong derived result or refusal under A's requested identity. Those scenarios were not executed here, so their exact current runtime outcome remains unverified. Test the actual CLI path, not a helper that receives already-consistent pins.

Lifecycle compaction is a related handoff. The application records available releases, while the engine protects dependencies it knows about. A retained probe showed an older release still marked available becoming unreadable after automatic compaction. Recheck this on the intended runtime when resuming News Lake, and register or preserve supported dependencies through the existing owner. Removing all compaction would avoid useful work rather than resolve ownership.

### Export policy needs inputs the caller did not ask to display

Both the Python and native export preparation derive expired capture IDs from capture rows present in the supplied read. A caller can legitimately request only article versions while the release still pins the corresponding captures. The code treats the missing policy input as an empty expired-ID set. The native path may then take its unchanged direct-export route without the missing expiry decision.

The fix belongs at export preparation: resolve the required captures from the exact release even when they are absent from the requested output. Keep missing evidence distinguishable from a completed decision that permits export. Reuse the native policy after comparing it with the intended behavior, then remove duplicate production enforcement. Loading and validating the whole release in Python is not required merely to recover these policy dependencies.

The native export pin is immutable, but the optional destination copies it to a fixed filename such as `news_versions.parquet`, replacing that path on a later export. A caller holding the earlier filename can therefore read different bytes. Return an immutable export reference or a release-specific destination and keep the movable channel separate.

There is a second, shared time-type defect. [News schema conversion](../../packages/news_lake/src/news_lake/storage/docspec/schema.py) represents timestamps as Arrow strings, and [canonical formatting](../../packages/news_lake/src/news_lake/context.py) preserves variable fractional precision. `12:00:00.1Z` is later than `12:00:00Z` as an instant, but sorts before it as text. Native merge uses string `min`, `max` and ordering; native capture expiry uses string comparison. This can choose the wrong newer value or redact content too early. Use typed chronological comparison while preserving source fields and precision. Include mixed fractional precision alongside the already required equality boundary. This finding is source-grounded, not a new runtime measurement.

### Recovery must invalidate local assumptions as well as restore rows

`ct-d8cf` can shrink from a general backend migration to specific remaining repairs:

- `ControlStore.claim()` reads the claimed epoch after releasing its transaction. Overlapping claims can give the first caller the second caller's epoch. Return the value established by the transaction.
- Native publication checks the epoch before the batch but does not carry it into each dataset commit. A later fenced metadata write can refuse after earlier native mutations already occurred. Check the maintained per-commit ownership boundary and preserve the engine's own stale-base protections.
- `abandon_cycle` clears `_known_ids` but leaves `_known_upsert_records`. After restoring A from a failed B update, a retry can consult cached B and suppress work that is absent from the restored data. Invalidate or rebind caches to the restored pins.
- Rollback prefers mutable committed state, which is saved after a batch. Reconcile partial durable commits with exact native operation results before deciding that the baseline is restored.

These are current source mechanisms. Their complete failure-path results still need focused verification when this parked product resumes. Native merge, change streams, compaction and operation reconciliation already exist; the audit does not establish a need for a replacement engine. The News adapter also needs to use the intended qualified runtime consistently rather than assuming a binary found on the shell path is that runtime.

### Missing observations and successful empty data are different states

`ct-tbrj` is an observation feature, not a missing meeting value. Congress.gov's `updateDate` describes the publisher's record. A capture timestamp describes retrieval. Neither proves that the exact detail endpoint was successfully read for that event without the associated endpoint and parsing evidence. The upstream comparison's hardcoded missing-destination note identifies a possible feature gap; it does not qualify every event's read state.

`ct-yr9o` concerns a genuine classification defect: the House parsers turn XML syntax failure into completed empty output. The common producer already owns unreadable decisions, so the smallest change is to stop swallowing that failure. Valid witness lists with no entries must stay successful and empty. The old measured cohort contained no bad body, and this defect does not explain the separately diagnosed Rules intake gap. Keep it with the next intentional pin change instead of initiating another broad replay.

The newly merged document-reference backfill requires unchanged values and refuses new unreadable decisions. This fix needs a later source-scoped transition that explicitly permits and verifies the changed failure state; it cannot borrow that backfill's equivalence proof.

## The three tickets added after the original ranking

These already had a separate [URL and recovery analysis](../experiments/url-normalization-revalidation-20261105/root-causes.md). This review reused its retained evidence and checked the current downstream paths.

| Ticket | One-line user value | Current state and root problem | Smallest useful end state |
| --- | --- | --- | --- |
| [ct-yci9](../../.tickets/ct-yci9.md) | Associate a document with the bill its evidence supports. | Document `f984b8439d21b0ef` says H.R. 4755, while agreeing source filenames lead e145 to assert H.R. 4775. Package selection checks disagreement among names; direct bill metadata has a separate path. | Apply a body-bound decision at package and direct-measure selection. Preserve literal filenames, bytes and links. Do not invent a package edition from a bill number. Verify final model and reader results. |
| [ct-5esu](../../.tickets/ct-5esu.md) | Find a saved document from a supported alternate URL spelling. | All retained exact source lookups passed. Percent-escape case and browser-space variants miss because public lookup deliberately preserves a narrower spelling than acquisition. | Add narrow fallback aliases while preserving exact keys, collision checks and all supported historical editions. Qualify download repairs separately; repaired addresses do not establish document identity. |
| [ct-rie2](../../.tickets/ct-rie2.md) | Recover an intended document and see the accepted result published. | Ordinary capture profile version 1 is valid. A requirements-bound campaign needs selected version-2 inputs, execution, acknowledged import and public attachment that e145 does not establish. Initial plan counts are not final gains. | Finish one bounded real cohort through the existing paths, reuse completed work, and replan read-only after imports. Keep target, candidate, body, relationship, occurrence and document counts distinct. |

The bill correction has one additional downstream trap: [`document-normalized.sql`](../../model/sql/document-normalized.sql) can refill a null package from `recovered_copy_fills`. A rejected association must remain rejected through that final fallback. Readers also combine direct document and meeting-context bill relationships; verify the intended direct association without removing useful context indiscriminately.

For recovery, final replanning must not silently rewrite the descriptor used to identify an import operation. The existing operation checks bind that descriptor as well as the request. Reuse the per-target ledger and acknowledged imports; report the final state separately from the original execution identity.

## Threads across the complete backlog

1. **Keep source statements separate from conclusions.** Filenames, meeting attachments, XML order, publisher update times and repaired addresses each establish particular facts. None automatically establishes a document's bill, date, interchangeable witness role, detail-read state or historical edition.
2. **Preserve meaning through retries and partial reads.** Unknown, unreadable, valid empty and unavailable are different outcomes. The same distinction connects malformed XML, optional reader failures, versions-only expiry, frozen receipt privacy and interrupted publication.
3. **Select once, then preserve that selection.** Exact release pins and parser versions lose their value when downstream helpers silently choose newer inputs, drop accepted older rows, or delete a completed phase before its last consumer.
4. **Reuse physical work without weakening identity.** Timestamp pruning must not permit duplicate logical IDs. Lookup aliases must not merge editions. Equivalent SQL edits should not force pointless reprocessing, while meaningful changes still need the affected rows recomputed.
5. **Deliver the research path before completing unrelated infrastructure.** Completing delivery of the earlier hearing, witness, testimony, recording and date repairs remains first. Some implementation merged during this audit; publication remains a separate step under the shared build hold. News Lake, canonical table renaming and optional labels retain their own product boundaries. Existing tests, source readings and publication evidence should reduce the work, with their limits kept explicit.

The useful News Lake sequence, when that product resumes, is logical-ID and chronological correctness, writer/recovery safety, exact-release derived reads, then export policy and optional label consumption. Performance measurement follows correctness on the same workload. These remain existing ticket owners, not a new set of epics.

## Completion, evidence and release coordination

The [frozen baseline](../../.cache/archive-release/investigations/mvp-etl-root-causes-round4-20261105T200959Z/baseline.json) records the ten assigned tickets and all ticket hashes. [Combined findings and backlog coverage](../../.cache/archive-release/investigations/mvp-etl-root-causes-round4-20261105T200959Z/combined-findings.json) link every original ticket and all current open tickets to its review. Detailed traces are in the [source-observation review](../../.cache/archive-release/investigations/mvp-etl-root-causes-round4-20261105T200959Z/source-observations-root-causes.md), [News release review](../../.cache/archive-release/investigations/mvp-etl-root-causes-round4-20261105T200959Z/news-release-root-causes.md) and [News backend review](../../.cache/archive-release/investigations/mvp-etl-root-causes-round4-20261105T200959Z/news-backend-root-causes.md).

The earlier reports cover [original ranks 1–15](production-mvp-root-causes-20261105.md), [16–30](production-mvp-root-causes-round2-20261105.md) and [31–45](production-mvp-root-causes-round3-20261105.md). Five HTML stage tickets were consolidated earlier, leaving 47 open; three additions brought the audit-start count to 50. During this review, another task closed `ct-syem` as satisfied using existing evidence and `ct-fd16` as deferred for lack of a current consumer. The **48 currently open tickets all have root-cause coverage**. Coverage does not mean implementation is complete; earlier reports retain their source-time findings, and the implementation waves own delivery status.

The source baseline was `c3ee2eec`. Main first advanced to `4d37a73` for URL documentation and tickets, then to `18049548` with completed MVP code repairs. The five source/lookup findings were reconciled against that merge; News Lake, the shared client and the runtime pin remained unchanged. Subsequent commits through the recorded completion head changed only documentation and tickets. The new positive bill-package registry handles a different qualified PDF and does not resolve the contradictory 4755/4775 case or its separate direct-measure path. Assigned ticket wording stayed unchanged; the three additions lost a trailing blank line. No tests, builds, pipeline jobs, corpus scans, acquisition, ticket changes, cleanup or deployment were performed by this audit.

The [audit status](../../.cache/archive-release/investigations/mvp-etl-root-causes-round4-20261105T200959Z/status.json) records the bill-selection dependencies and technical owner for the release coordinator. No implementation task was launched. The existing hold on full builds, publication and new shared catalog writes remains in effect until the implementation waves are ready for their coordinated freeze.
