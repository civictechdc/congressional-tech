# Publication rescore and remaining findings

Three independent reviews reassessed **all 168 original entries** against the
six original dimensions at `90982181ad95366c12bb08d2b9789ea4f9042216`.
Eleven narrow grade updates incorporate the eight reviewed fixes merged at
`f438264f791956abd37177e9d334d00eb010e169`. Source and test-file equivalence was
checked after integration. Saved evidence and new local tests support this
assessment; no new full-corpus or hosted qualification was performed. Closed
tickets did not determine grades.

The initial review found 107 resolved entries, 30 intentional tradeoffs, 27 partial
improvements and four unresolved entries. After this batch: **116 resolved,
30 intentional tradeoffs, 20 partial and 2 unresolved**. Twenty-three rows
retain explicit actions across twelve open follow-up tickets. Multiple entries
can describe one underlying problem. The eight scoped fixes are complete; larger
local-controller structure and costs remain open.

Grades are consequence-weighted judgments, not numerical averages. A resolved
entry can retain a B for an intentional full read or exact-value allocation.
The general Catalog remains the clearest architecture cost: C efficiency and
C+ debt, with B- overall. Retained measurements show 5.085 GB highwater during
loading and 7.310 GB across full local preparation. They establish a remaining
cost; without a matched baseline they do not prove an aggregate improvement.

## Architecture assessment

An independent synthesis grades this examined scope **B- overall**: correctness
B+, efficiency C+, developer/operator experience B-, thoughtfulness A-, and
architectural debt C+. These are consequence-weighted judgments, not averages of
function grades. Strong evidence preservation and conditional writes earn credit;
the general Catalog, duplicated local/cloud preparation ownership, runtime loading
and normal journal checkpoint cost still dominate architecture and operating effort.

The user prioritized **efficiency and architectural debt**. Priority 1 work now
covers repeated mapping/checkpoint work (`ct-2uwd`, `ct-v6ao`), preparation memory
(`ct-m9ry`), broad-search cost (`ct-4zer`), and one explicit runtime/accepted-plan
owner (`ct-piku`, `ct-bpyj`). Measure work counts and resource use on comparable
cases; do not add overlapping timing percentages. Resource policy and recovery
diagnostics follow.
This assessment covers the 168 flagged entries and their reviewed replacements,
not a fresh review of all 372 functions in the original exam.

The concurrent Grok/Cursor `/scripts` refactor is outside this pinned assessment.
Its changes remain untouched; the open script tickets provide acceptance criteria
for reviewing that work. They should close only when new evidence demonstrates the
specific finding is addressed.

## Prioritized follow-ups

These open tasks are linked to the current batch. All depend on its completed
audit. The accepted-plan work also depends on the runtime-owner fix and local
proof/custody fixes; local event ownership depends on checkpoint work. Memory
profiling follows proof and reader cleanup. No dependency cycles exist.

| Priority | Ticket | Outcome |
| --- | --- | --- |
| 1 | [ct-2uwd](../.tickets/ct-2uwd.md) | Consume one verified mapping write receipt |
| 2 | [ct-tdsx](../.tickets/ct-tdsx.md) | Define bounded startup handling for mandatory recovery status |
| 2 | [ct-o6d1](../.tickets/ct-o6d1.md) | Define the exact-value browser memory and complete-export policy |
| 1 | [ct-piku](../.tickets/ct-piku.md) | Make recovery runtime imports belong to the declared runtime |
| 1 | [ct-4zer](../.tickets/ct-4zer.md) | Measure broad browser search cost and choose a bounded improvement |
| 1 | [ct-v6ao](../.tickets/ct-v6ao.md) | Reduce normal publication checkpoint work with crash proof |
| 1 | [ct-bpyj](../.tickets/ct-bpyj.md) | Share accepted viewer plans across local and cloud publication |
| 3 | [ct-76n5](../.tickets/ct-76n5.md) | Expose retained incomplete build reconciliation steps |
| 2 | [ct-2ut4](../.tickets/ct-2ut4.md) | Give local recovery one event owner and derived progress |
| 1 | [ct-m9ry](../.tickets/ct-m9ry.md) | Measure publication Catalog state before choosing a narrower reader |
| 3 | [ct-5jqd](../.tickets/ct-5jqd.md) | Report bounded per-object reconciliation progress |
| 3 | [ct-h73z](../.tickets/ct-h73z.md) | Use original-attempt descriptor at workflow resume boundary |

## Keep decisions

Keep provider-specific retry and absence rules, JSON/gzip byte formats, unique
versus fixed temporary-file ownership, immutable-file installation, and fsync
requirements separate. Keep required Explorer inputs in the shared Pages build,
archive membership support, complete provenance redraw, exact source values,
and independent freshness checks that explicitly do not claim a multi-object
transaction. Each affected entry retains its reason in the JSON record. These
are decisions recorded under audit `ct-2d3k`, not missing implementation tickets.

Every actionable finding has a ticket; repeated findings share one ticket.
The machine-readable [complete gradebook](package-overlap-rescore-20261019.json)
retains all six original/current grades, current source locations, read evidence,
confidence, original tickets, follow-up tickets and keep decisions. Historical
original reports and qualification receipts remain unchanged.

## Complete assessment

C: correctness; E: efficiency; DX: developer/operator experience; T: thoughtfulness;
D: architectural debt (higher means less unnecessary debt). Locations refer to
each row's reviewed revision. JSON retains original and pre-cleanup grades and
closed fix tickets; the last column here shows only open follow-up work.

| Original entry | Old overall | C | E | DX | T | D | Overall | Disposition | Open work |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `.github/scripts/publication-budget.py:7:check` | B+ | A- | A- | A- | A- | A- | A- | resolved | Keep / resolved |
| `.github/workflows/deploy-pages.yml:1:Pages build and deploy workflow` | C+ | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | Keep / resolved |
| `.github/workflows/deploy-pages.yml:54:inline Explorer stage prerequisite` | C+ | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | Keep / resolved |
| `apps/site/scripts/stage-document-reviews.py:8:module build entry` | C+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-bootstrap.mjs:8:worker.onmessage` | B+ | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-bootstrap.mjs:20:(closure)` | C+ | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/src/components/filename-bootstrap.mjs:21:worker.onerror` | C+ | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-bootstrap.mjs:22:(closure)` | C+ | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/src/components/filename-bootstrap.mjs:22:window.filenameViewerApi` | C+ | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-bootstrap.mjs:25:abort` | B | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:10:text` | B- | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | ct-4zer |
| `apps/site/src/components/filename-catalog.mjs:11:normalized` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:47:sourceContext` | B+ | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:69:rangeFile` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:71:slice` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:95:createFilenameCatalog` | B | B+ | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:104:binary` | B+ | B+ | B+ | B+ | A- | B+ | B+ | intentional tradeoff | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:124:membersOf` | B | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:163:table` | B- | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:176:prefetchColumns` | B- | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:194:read` | B+ | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | ct-4zer |
| `apps/site/src/components/filename-catalog.mjs:202:observationStore` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:214:scalarRecord` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:225:sourceRecord` | B+ | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | ct-o6d1 |
| `apps/site/src/components/filename-catalog.mjs:231:selected` | C+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:242:column` | C | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | ct-4zer |
| `apps/site/src/components/filename-catalog.mjs:245:(closure)` | B- | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:255:search` | C+ | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | ct-4zer |
| `apps/site/src/components/filename-catalog.mjs:278:matches` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-catalog.mjs:319:resolve` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-observations.mjs:16:decode` | B | B+ | B | B+ | A- | B | B | intentional tradeoff | ct-o6d1 |
| `apps/site/src/components/filename-observations.mjs:35:refsFor` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-observations.mjs:63:read` | B+ | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | ct-o6d1 |
| `apps/site/src/components/filename-observations.mjs:67:scan` | B+ | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | ct-4zer |
| `apps/site/src/components/filename-observations.mjs:81:matchingSources` | B | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | ct-4zer |
| `apps/site/src/components/filename-observations.mjs:85:(closure)` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/components/filename-publication.mjs:4:read` | B+ | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/src/components/filename-publication.mjs:37:watchPublication` | B+ | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/src/components/filename-recoveries.mjs:2:loadRecoveries` | B+ | B+ | B | B+ | A- | B+ | B+ | intentional tradeoff | ct-tdsx |
| `apps/site/src/components/filename-reviews.mjs:1:verifiedJson` | B+ | A- | B+ | B+ | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/src/components/filename-worker.mjs:4:self.onmessage` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/src/pages/filenames.astro:1:template extraction frontmatter` | B | A- | A- | A- | A- | A- | A- | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:6:display` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:19:filenameDate` | B | A- | A- | A- | A- | A- | A- | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:23:api` | B+ | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:140:openDetail` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:167:renderSources` | B+ | A- | A- | B+ | A- | B+ | A- | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:226:evidenceUrl` | B+ | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:303:renderOrigin` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:422:renderFilename` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:568:renderCurrentOrigin` | B+ | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:575:(closure)` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:611:renderDetails` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:635:goToPage` | B | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:654:(closure)` | B+ | A- | B- | B+ | A- | B+ | B+ | intentional tradeoff | ct-o6d1 |
| `docs/youtube-coverage/research/filename-viewer.mjs:656:(closure)` | B | A- | A- | B+ | A- | B+ | A- | resolved | Keep / resolved |
| `docs/youtube-coverage/research/filename-viewer.mjs:657:initialization block` | B+ | B+ | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `.github/workflows/publish-filename-viewer.yml:62:publish (workflow job)` | C+ | B+ | B+ | B | B+ | B+ | B+ | partial | ct-h73z |
| `apps/site/scripts/publish-viewer-r2.py:38:open_public` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:61:read_identity` | B+ | B+ | A- | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:79:implementation_identity` | C+ | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:85:dependency_fingerprint` | B | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:99:recovery_inputs` | B+ | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:108:verify_recovery_status` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:126:check_recovery_inputs` | B | B+ | B | B+ | A- | B+ | B+ | intentional tradeoff | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:142:prepared_files` | B | B+ | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:181:store_recovery_index` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:198:recovery_for_publication` | B | B+ | B | B+ | B+ | B | B+ | partial | ct-bpyj |
| `apps/site/scripts/publish-viewer-r2.py:204:select_recoveries` | B | B+ | B+ | B | B+ | B | B+ | partial | ct-bpyj |
| `apps/site/scripts/publish-viewer-r2.py:223:accept_recoveries` | B | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:285:upload` | C+ | B+ | B | B | B+ | B | B | partial | ct-bpyj |
| `apps/site/scripts/publish-viewer-r2.py:310:upload.transfer` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:368:bootstrap_pages` | C | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:385:bootstrap_pages.download` | B | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:397:refresh_recoveries` | B+ | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:433:run` | C+ | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-viewer-r2.py:470:__main__ (CLI entry block)` | B- | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:27:cloud_clear` | B | B+ | B | B+ | B+ | B+ | B+ | intentional tradeoff | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:32:verify_import` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:72:verify_coverage` | B- | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:78:load` | B- | B+ | A- | C+ | B | C+ | B- | unresolved | ct-piku |
| `scripts/dispatch_corpus_recovery_publication.py:85:rebuild_retained_catalog` | B- | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:94:run` | C+ | B+ | C+ | B- | A- | C+ | B- | partial | ct-bpyj |
| `scripts/dispatch_corpus_recovery_publication.py:113:run.journal` | B- | B+ | B | C+ | A- | C+ | B- | partial | ct-2ut4 |
| `scripts/dispatch_corpus_recovery_publication.py:177:run.protected_check` | B+ | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:188:run.ContinuedClient.put_object` | B- | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:209:run.Store.read` | B | B+ | B | B- | B+ | C+ | B | unresolved | ct-bpyj |
| `scripts/dispatch_corpus_recovery_publication.py:214:run.Store.put` | B | A- | B | B | B+ | C+ | B | partial | ct-bpyj |
| `scripts/dispatch_corpus_recovery_publication.py:218:run.Store.save_derived` | B | A- | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:223:run.Store.read_derived_file` | B | A- | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:228:run.Store.put_derived_file` | B | A- | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:231:run.Store.put_catalog_manifest` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/dispatch_corpus_recovery_publication.py:238:run.catalog_phase` | B- | B+ | B | B | A- | B | B | partial | ct-76n5 |
| `scripts/dispatch_corpus_recovery_publication.py:259:run.mapping_phase` | B+ | A- | B | B+ | A- | B | B+ | partial | ct-2uwd |
| `scripts/dispatch_corpus_recovery_publication.py:267:run.prepared_phase` | B+ | A- | B | B | A- | B | B+ | partial | ct-bpyj |
| `scripts/dispatch_corpus_recovery_publication.py:274:run.publication_phase` | B | A- | B | B | A- | B | B+ | partial | ct-bpyj |
| `scripts/guarded_recovery_publication_client.py:45:GuardedPublicationClient.check_guard` | B+ | B+ | A | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/guarded_recovery_publication_client.py:49:GuardedPublicationClient.verified_result` | B+ | A- | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `scripts/guarded_recovery_publication_client.py:84:GuardedPublicationClient.put_object` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/guarded_recovery_publication_client.py:155:GuardedPublicationClient.upload_file` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/pipeline_status.py:113:continuation` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/publish_corpus_recovery_mappings.py:14:publish_mappings` | B+ | A- | B | B+ | A- | B | B+ | partial | ct-2uwd |
| `scripts/recovery_guards.py:19:active_cloud_writers` | B- | B+ | B | B+ | B+ | B+ | B+ | intentional tradeoff | Keep / resolved |
| `scripts/recovery_guards.py:86:RecoveryGuard._cloud` | B+ | B+ | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/recovery_guards.py:106:RecoveryGuard.boundary` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/recovery_publication_continuation.py:21:Continuation.__init__` | B+ | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `scripts/recovery_publication_continuation.py:37:Continuation.flush` | B | A- | B | B+ | A- | B | B+ | partial | ct-v6ao |
| `scripts/recovery_publication_continuation.py:48:Continuation.save` | B | B+ | B | B+ | B+ | B+ | B+ | intentional tradeoff | Keep / resolved |
| `scripts/recovery_publication_continuation.py:60:Continuation.phase` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/recovery_publication_continuation.py:73:Continuation.record` | B- | B+ | B | B+ | B+ | B | B+ | partial | ct-v6ao |
| `scripts/recovery_publication_continuation.py:102:Continuation.reconcile` | B+ | A- | B+ | B | A- | B+ | B+ | partial | ct-5jqd |
| `scripts/recovery_publication_continuation.py:124:Continuation.replay` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/recovery_publication_continuation.py:160:DurableJournal.__init__` | B+ | B+ | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/recovery_publication_continuation.py:182:DurableJournal.restore` | C+ | B+ | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/recovery_publication_continuation.py:205:DurableJournal.record` | C+ | B+ | C+ | B | A- | B | B | intentional tradeoff | ct-v6ao |
| `scripts/viewer_publication_attempt.py:21:content_identity` | C+ | B+ | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `scripts/viewer_publication_attempt.py:37:prepare` | C | B+ | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/viewer_publication_attempt.py:56:prepare.build` | C+ | B+ | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/viewer_publication_attempt.py:104:verify_prepared` | C+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/viewer_publication_attempt.py:138:verify_github_artifact` | B+ | B+ | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `scripts/viewer_publication_attempt.py:153:publish` | C+ | B+ | B | B | A- | B | B+ | partial | ct-bpyj |
| `scripts/viewer_publication_attempt.py:186:publish.guard` | B | B+ | B | B+ | B+ | B+ | B+ | intentional tradeoff | Keep / resolved |
| `scripts/viewer_publication_attempt.py:200:publish.after_write` | B+ | A- | B | B+ | B+ | B | B+ | partial | ct-v6ao |
| `scripts/viewer_publication_attempt.py:213:publish.ContinuedClient.put_object` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_aliases.py:47:catalog_aliases` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_details.py:45:publish_details` | B- | A- | B | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_details.py:58:publish_details.observation_counts` | B- | A- | A- | B+ | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/scripts/filename_details.py:70:publish_details.encode` | B- | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_navigation.py:7:publish_navigation` | B+ | A- | B+ | B+ | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/scripts/filename_observations.py:15:json_bytes` | A- | A | B | A | A- | A | A- | intentional tradeoff | Keep / resolved |
| `apps/site/scripts/filename_observations.py:20:Blocks.__init__` | B | A- | B+ | A- | A- | B+ | A- | resolved | Keep / resolved |
| `apps/site/scripts/filename_observations.py:26:Blocks.append` | B- | A- | B | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_observations.py:34:Blocks.flush` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_observations.py:49:Blocks.close` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_observations.py:55:publish_observations` | B | A- | B | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_observations.py:80:verify_observations` | B+ | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | Keep / resolved |
| `apps/site/scripts/filename_observations.py:90:verify_observations.read_block` | B- | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_recoveries.py:15:accepted_rows` | B | A- | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_recoveries.py:35:index_recoveries` | B- | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_review_binding.py:20:load_identities` | B | A- | A- | B+ | A- | B+ | A- | resolved | Keep / resolved |
| `apps/site/scripts/filename_review_binding.py:30:bind` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_review_binding.py:56:identities_from` | B+ | A- | B | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_review_binding.py:72:main` | C+ | A- | B- | B | B+ | B | B | partial | ct-m9ry |
| `apps/site/scripts/filename_reviews.py:12:export_reviews` | B | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/filename_reviews.py:81:extract_archive` | B | A- | B+ | B+ | A- | B+ | A- | resolved | Keep / resolved |
| `apps/site/scripts/publish-filename-viewer.py:51:verify` | B+ | A- | A- | B+ | A- | B+ | A- | resolved | Keep / resolved |
| `apps/site/scripts/publish-filename-viewer.py:73:fetch` | B- | A- | B | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `apps/site/scripts/publish-filename-viewer.py:96:write_u32` | B+ | A- | A- | A | A- | A- | A- | resolved | Keep / resolved |
| `apps/site/scripts/publish-filename-viewer.py:109:repack_and_verify` | B | A- | B | B+ | A- | B+ | B+ | intentional tradeoff | Keep / resolved |
| `apps/site/scripts/publish-filename-viewer.py:132:publish` | C+ | A- | C+ | B | A- | B | B | partial | ct-m9ry |
| `docs/youtube-coverage/research/scripts/view_document_filenames.py:270:Catalog.__init__` | C | A- | C | B | B+ | C+ | B- | partial | ct-m9ry |
| `docs/youtube-coverage/research/scripts/view_document_filenames.py:393:Catalog.source_mask` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `docs/youtube-coverage/research/scripts/view_document_filenames.py:516:Catalog.record` | C | A- | B | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `docs/youtube-coverage/research/scripts/view_document_filenames.py:546:Catalog.document` | C | A- | B | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `docs/youtube-coverage/research/scripts/view_document_filenames.py:552:Catalog.review_rows` | B- | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/catalog_cache.py:53:LocalStore.keys` | B | A- | A- | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/catalog_cache.py:57:LocalStore.put` | B- | A- | B+ | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/catalog_publication.py:132:publish_catalog` | B- | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/catalog_validation.py:23:_validator_identity` | B+ | A- | A- | B+ | A- | B+ | A- | resolved | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/catalog_validation.py:52:validate_catalog_pair` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/document_index.py:681:validate_document_indexes` | B+ | A- | B | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/document_index.py:2659:selected_filename_path` | B | B+ | B | B+ | B+ | B+ | B+ | resolved | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/r2.py:53:_configure_retries` | B+ | B+ | A- | B+ | B+ | B+ | B+ | intentional tradeoff | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/r2.py:58:_configure_retries.retry` | B+ | B+ | A- | B+ | B+ | B+ | B+ | intentional tradeoff | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/r2.py:164:R2Store.read` | B | B+ | B | B+ | B+ | B | B+ | intentional tradeoff | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/r2.py:192:R2Store.put` | B+ | A- | B+ | B | B+ | B | B | intentional tradeoff | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/r2.py:313:R2Store.put_derived_file` | B+ | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
| `packages/congress_api/src/congress_api/retention/raw_catalog.py:349:_publish_result` | B- | A- | B+ | B+ | A- | B+ | B+ | resolved | Keep / resolved |
