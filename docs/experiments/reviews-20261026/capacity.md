# Publication capacity, acknowledgment and recovery review

## Findings and decision

The combined review found two resource-bound defects. Both now have focused fixes. No additional blocking defect was found in the traced upload acknowledgment, continuation, local recovery or status paths.

1. **WARNING — unbounded public Parquet smoke response.** At reviewed source `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`, both four-byte range probes called `response.read()` without a limit. A malformed 206 response with plausible headers could cause an EOF read. `packages/viewer_publication/src/viewer_publication/publish_viewer_r2.py:414` and `:449` now use `read(5)`: four expected magic bytes and one overflow sentinel. Fix `ff98a4e448665bb6150cc9c1a00f7f5b566f4937`, rebased equivalent `deb9cfe6e80ad90d768ef629676afae69a267846`. Both new tests failed with `[-1]` instead of `[5]` before the fix and pass afterward. This adds no successful-upload readback.
2. **WARNING — occurrence buffer ignored its byte allowance.** The occurrence subagent found that the writer limited row count while bypassing `DecodedPolicy.writer_buffer_bytes`. The fix is integrated in `6183938fcb2b0842d5e1f59072383aa7dd251d32`. Independent inspection confirms both standalone and combined callers pass policy/metrics, the writer refuses a single oversized row and flushes before exceeding its retained-Python-byte allowance (`filename_exports.py:346`, `:390`, `:449`; `filename_native.py:293`). Semantic rows, order and slices remain stable. Earlier flushes can change Parquet groups, browser ranges, bytes and digests. This allowance measures retained Python rows and list overhead; it is not a process-RSS or native encoder allocation guarantee.

The inventory and journal delegates report APPROVE. One nonblocking duplication remains: the local saved-phase recovery route walks its directory twice. Hosted verification walks once. No follow-up redesign is proposed here.

## Patch summary and scope

Initial combined source reviewed: `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`. Final integration delta inspected: `ad222085..6183938fcb2b0842d5e1f59072383aa7dd251d32`, plus the unique bounded-smoke fix above. Review branch was rebased onto exact `6183938f`; source fixes already integrated by other owners were not replayed.

The change admits a realistic full-release inventory within independent count and byte ceilings, removes repeated whole-state copying/serialization, reuses issued file proofs and synced journal bytes, and accepts successful PUT responses. Remote reads resolve uncertain outcomes, load required inputs/history, or perform bounded public gateway smoke checks. Preparation still binds exact inputs, producer identity and accepted files before publication.

Review work was static except the explicit two-test reproduction and focused 47-test smoke/upload regression. No publication, production preparation, deployment or operational-setting change ran in this review. The filename publisher remains manually disabled; selected-v5 refusal remains in place.

## Function trace

Paths abbreviated below: `VP` means `packages/viewer_publication/src/viewer_publication/`; `SP` means `scripts/publication/`. Line references describe final inspected source plus the two-line smoke fix.

| Function / method | File:line | Inputs | Output | Verified behavior |
| --- | --- | --- | --- | --- |
| `require_publication_client` | VP/client.py:33 | SDK client | accepted client or refusal | Requires single-attempt requests; avoids hidden PUT retries. |
| `write_lock`, `check_guard` | VP/client.py:68,86 | key, conditions | guarded scope | Independent immutable keys can progress; shared mutable writes serialize. |
| `confirm_transfer` | VP/client.py:96 | receipt, exact request | boolean | Consumes issuing-client receipt without network read. |
| `GuardedPublicationClient.put_object` | VP/client.py:124 | conditional request, body/proof | ETag and receipt | Records intent before PUT; successful response is acceptance; exceptions reconcile once without resend. |
| `_upload_file` | VP/client.py:231 | path, issued proof | transfer receipt | Streams one conditional PUT and reuses current file custody. |
| `ContinuedPublicationClient.put_object` | VP/client.py:253 | original request | saved result or guarded PUT | Replay requires same condition/body and preserves saved acknowledgment. |
| `publish_manifest_pointer` | VP/client.py:269 | expected version, pointer | conditional result | Mutable pointer retains original condition. |
| `write_transition`, `apply_event` | VP/continuation.py:99,127 | state and event | one validated state change | Avoids copying the growing write ledger. |
| `_restore`, `flush` | VP/continuation.py:157,160 | bounded checkpoint | validated state / atomic checkpoint | Checks raw and canonical byte limits. |
| `save`, `accept_saved` | VP/continuation.py:180,195 | synced bytes, file proof | saved custody proof | Accepted evidence hardlinks already synced bytes; conflicting evidence refuses. |
| `phase` | VP/continuation.py:210 | files/inventory/action | accepted phase | Checks names, custody, counts and serialized bytes before accepting. |
| `checked_event`, `record` | VP/continuation.py:265,291 | event | preadmitted transition | Exact JSON delta includes Unicode, commas, versions and refusals. |
| `reconcile`, `replay` | VP/continuation.py:341,389 | saved writes/current request | recovered acknowledgment | Acknowledged writes incur no GET/HEAD; only uncertain writes require exact body resolution. |
| `DurableJournal.restore` | VP/continuation.py:448 | remote event prefix | accepted local history | Checks binding, sequence, nonce, chain and bounds before replacing state. |
| `DurableJournal.record`, `_append` | VP/continuation.py:514,538 | event | durable accepted event | Synced intent precedes conditional cloud PUT; accepted evidence reuses same bytes. |
| `prepare`, `verify_prepared` | VP/attempt.py:48,214 | original inputs/output custody | accepted preparation | Preserves input/producer binding and exact phase membership. |
| `publish`, nested `guard` | VP/attempt.py:323,357 | artifact, original attempt | publication result | Restores history before guards and conditional writes; completed recovery reuses saved acceptance. |
| `read_local_journal` | VP/local.py:29 | bounded local history | validated reconstruction | Chain/event checks precede replacing derived state. |
| `LocalContinuation.flush`, `record` | VP/local.py:112,122 | checkpoint/event | fsynced authoritative record | Appends before applying; preserves versions-map identity. |
| `verify_preparation_checkpoint` | VP/resume.py:158 | descriptor, exact files | accepted checkpoint | Original artifact/input custody remains required; 128 MiB receipt bound is independent. |
| status `continuation` | SP/pipeline_status.py:113 | supplied observation | status data | Reads bounded evidence without mutation or granting resume/public proof. |
| `store_recovery_index` | VP/publish_viewer_r2.py:257 | recovery bytes | immutable descriptor | Success requires no readback; collision resolution remains exceptional. |
| `public_probe`, `public_probe_selected` | VP/publish_viewer_r2.py:379,419 | selected manifest/public gateway | smoke success or refusal | Bounded controls, supporting HEADs and bounded PAR1 range sample. |
| `upload` | VP/publish_viewer_r2.py:460 | accepted plan/files, guards | pointer/result | Reuses transfer proofs, keeps conditional writes and probes gateway before pointer acceptance. |
| `source_files` | VP/release_identity.py:20 | maintained source tree | hashed producer sources | Added maintained publishers/constants/DocSpec modules; cache reuse requires unchanged file custody. |
| `run_preparation` | SP/prepare_workflow_resume.py:92 | job start, checkpoint | bounded child outcome | Checkpoint validation consumes the same absolute deadline; refuses launch after expiry. |

The separate `ConditionalManifestPublisher` helper was inspected as a sibling, but it is not the deployed artifact-backed publication call path. No unrelated change is proposed.

## Data flow and invariants

- Preparation binds selected inputs and maintained producer hashes. File validation issues custody proofs, and accepted phases retain exact identities. `attempt.py:214` rechecks these before `publish` uses them at `:325`. Changing the maintained publisher now invalidates old producer identity through `release_identity.py:38`; use a fresh accepted preparation.
- A write moves from durable intent to one conditional PUT to acknowledged receipt (`client.py:124`). `verified` in persisted state means acknowledged success or resolved uncertainty; it does not assert a fresh remote-byte read. Lost acknowledgments resolve exact bytes once, while acknowledged replay returns saved evidence (`continuation.py:341,389`).
- Journal acceptance requires nonce-bound local evidence plus successful conditional remote append (`continuation.py:538`). Full remote history is input loading on restore, not successful-upload verification. A full bounded cloud prefix can still occupy memory up to its journal allowance; no streaming-format claim is made.
- Count ceilings and byte ceilings are independent (`continuation.py:26–33`). Exact state admission precedes journal/payload mutation. Derived checkpoint cadence is 1,024 events; durable intent/history, rather than the latest JSON cache, owns recovery.
- Local reconstruction applies one event to unpublished state and preserves the live protected-versions dictionary (`local.py:29,122`). Its current ceilings are 262,850 events and 512 MiB history, including checkpoint headroom (`local.py:16–18`). Status reports these observations without reconciling remote state (`pipeline_status.py:113`).
- Pointer mutation still checks original raw/accepted/viewer versions (`attempt.py:357`; publisher upload control checks). Neither success acknowledgment nor a public smoke check substitutes for these guards.

## Test behavior and concrete boundaries

| Evidence inspected | Trace / expected behavior |
| --- | --- |
| `.github/tests/test_viewer_r2.py:414` | Oversized range response has plausible headers; probe reads five bytes, rejects before mutable manifest write. Red before fix, green after. |
| `test_filename_native_upload.py:74` | Native selected-route equivalent records `[5]`; malformed range fails without EOF consumption. Red before fix, green after. |
| `test_recovery_viewer_transfers.py:58` | Normal upload: zero payload GETs; lost acknowledgment: one GET, one PUT; public probes remain separate. |
| `test_recovery_viewer_transfers.py:87` | Receipt binds issuing client, body size/hash and exact target; forged receipts do not skip transfer. |
| `test_publication_capacity.py:74` | 100,000 fake payloads, interrupted/recovered through maintained state methods; per-event evidence/cache writes counted. No real 100,000-payload build or network qualification. |
| `test_publication_capacity.py:153,178,195,240,258,281` | Count/byte admission, exact deltas, checkpoint cadence, worst noncoalesced event order and Unicode restore refusal. |
| `test_local_continuation.py:17,30,46,71` | No ledger copy, history beyond old cap, phase recovery without checkpoint, uncertain-body resolution without duplicate PUT. |
| `test_local_continuation.py:148,169,199,224,246` | Corruption/failed sync refuse; event fsync precedes payload; byte limits apply; guard versions retain object identity. |
| `SP/tests/test_pipeline_status.py:118,218,259,283,297` | Durable evidence is observable; large receipt admitted; current local events visible; stale cache explicitly labelled; no remote/public proof inferred. |
| `test_release_identity.py:48` | Parameterized mutations of maintained publisher/constants/DocSpec modules change source identity. Static inspection of new assertions. |
| `SP/tests/test_preparation_checkpoint.py:355` | Fake verification consumes 70/100 seconds or exceeds deadline at 110; child gets only 30 seconds or is never launched. Static inspection of new assertions. |
| `test_filename_observations.py:343,370` | Both occurrence callers flush below byte budget and refuse one oversized row; order/slices stable. Delegate ran four red reproductions and 50 focused passes. |

Executed here before rebase: 47 passed, two subtests passed in 6.40s across `.github/tests/test_viewer_r2.py`, `test_filename_native_upload.py`, and `test_recovery_viewer_transfers.py`. Logs: `/tmp/ct-capacity-review-smoke-red.txt` (two failures before fix), `/tmp/ct-capacity-review-smoke-green.txt`. `git diff --check` passed. This focused result is not a claim of execution at the eventual final merged SHA.

Integration-owner logs inspected separately: initial combined 723 publication checks, 235 data checks, 154 JavaScript checks; final `6183938f` follow-ups 264 cross-cutting Python checks, 126 renderer/native checks and 154 JavaScript checks. Follow-up counts overlap earlier coverage and are not additive unique tests. Logs `/tmp/ct-post-review-integration-20261026.log`, `/tmp/ct-post-review-occurrence-20261026.log`, `/tmp/ct-post-review-js-20261026.log`. These are execution by the integration owner, not executions by this review.

## Final delta review

Reviewed only the new delta after the initial combined review. The added producer sources feed the existing byte-hash/custody cache, so maintained implementation edits now invalidate preparation. The preparation supervisor uses `start + deadline_seconds`, rechecks after checkpoint validation and derives the child wait from the same deadline. Occurrence policy now reaches both callers and the writer checks retained bytes before appending. No extra blocker was found in these changes.

The capture-cache/source-resume changes and GPO timestamp repair are outside this review's primary publication scope. Their diffs were inspected for shared effects: exact capture batches replace shape-only cache admission, interpreted-file identity is saved/checked on resume, and failed retrieval sections contribute retained check timestamps. Detailed domain review remains with their respective integration owners; no independent execution claim is made here.

VERDICT: APPROVE for `6183938fcb2b0842d5e1f59072383aa7dd251d32` plus bounded-smoke fix `ff98a4e448665bb6150cc9c1a00f7f5b566f4937`.

Justification: the two concrete resource defects are fixed, successful PUTs remain accepted without routine payload GET/HEAD, and required custody/conditional/recovery checks remain. Coverage of changed paths: ADEQUATE for scoped local fixes. Confidence: HIGH for the traced paths; production full-release qualification remains unmeasured.

Owned branch: `codex/v6-capacity-merged-review`. Original backup `codex/v6-capacity-before-merged-review` preserves `2ffb2f184c42a506c8749eb4c31031f2c356405e`; final-delta backup `codex/v6-capacity-before-final-delta-20261026` preserves `ff98a4e448665bb6150cc9c1a00f7f5b566f4937`. No push or merge was performed by this reviewer.
