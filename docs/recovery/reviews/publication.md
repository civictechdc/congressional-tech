# Independent publication review

**VERDICT: APPROVE for local implementation.** No remaining correctness blocker found in the reviewed publication changes after `30819aa` and `95e429d`. This review does not establish live publication or deployment.

Reviewed the integration tree through `b1515a5`, then the publication tree through `95e429d` for the final T10 changes and related fixes. The integration tree must include `8458882`, `30819aa`, and `95e429d` (or equivalent cherry-picked commits) for this verdict to apply. I did not modify publication source.

## Findings first

1. **Resolved blocker — existing immutable catalog locator.** Before `30819aa`, `GuardedPublicationClient.put_object` replaced a definite 412 condition refusal with `ValueError` when the existing locator contained a different release. The maintained viewer publisher deliberately catches `ClientError` 412 for this case. `30819aa` preserves that error and removes the definitely refused intent from continuation state. The updated viewer-transfer probe includes a pre-existing locator, and the continuation probe checks that the refusal does not poison resume. Evidence: `scripts/guarded_recovery_publication_client.py:126-143`, `scripts/recovery_publication_continuation.py:73-74`, `apps/site/scripts/publish-viewer-r2.py:248-253`, `tests/test_recovery_publication_continuation.py:94-107`, `tests/test_recovery_viewer_transfers.py:69` in the publication tree.
2. **Observation — validation scope.** The dispatcher restart probe invokes the actual dispatcher and continuation but substitutes the catalog builder, mapping publisher, and viewer implementations. Separate tests exercise actual pair-proof reuse and actual viewer upload through the guarded client. This is compositional offline evidence, not one execution of the whole production pipeline. Evidence: `tests/test_dispatch_corpus_recovery_publication.py:75-155`, `tests/test_catalog_pair_validation.py:34-65`, `tests/test_recovery_viewer_transfers.py:60-87`. No live credentials or remote writes were used.

## Exploration notes

H1: A catalog no-op can reach viewer preparation with the selected source files present. Confirmed: `Store.read` saves the selection and immutable pair while `_rebuild_catalog` calls `read_catalog` before its unchanged branch (`scripts/dispatch_corpus_recovery_publication.py:200-205`; `packages/congress_api/src/congress_api/retention/raw_catalog.py:68-75,99-111`). The dispatcher probe checks that preparation sees both saved files.

H2: A lost acknowledgment can cause a duplicate request after restart. Refuted for accepted receipts: the guarded client writes intent before PUT, reads complete bytes once, persists verified identity, and continuation reconciles current bytes/version before replay (`scripts/guarded_recovery_publication_client.py:117-148`; `scripts/recovery_publication_continuation.py:98-135`). A definitely refused immutable locator now leaves no uncertain intent.

H3: Parallel payload writes can bypass the guarded write boundary or mix stale proof. Refuted within the reviewed call path: the upload uses the injected client, per-key locks permit immutable overlap, shared writes take the common lock and fresh guard, and a transfer receipt binds client identity, bucket, key, size, SHA-256, and current ETag (`scripts/guarded_recovery_publication_client.py:32-63,138-160`; `apps/site/scripts/publish-viewer-r2.py:216-245`).

H4: T10 proof can survive changed source bytes, manifest, expected imports, validator code, or process restart. Refuted: the proof binds resolved root, exact normalized manifest, both file identities including ctime, expected bodies, validator identity/code/source-file identity, and PyArrow version; it is kept only in memory (`packages/congress_api/src/congress_api/retention/catalog_validation.py:14-47,59-85`). Tests mutate same-size bytes while restoring mtime, replace validator code, and vary root/manifest/expected bodies.

## Patch and function trace

| Function or method | Evidence | Input → output | Verified behavior |
| --- | --- | --- | --- |
| `run` dispatcher | `scripts/dispatch_corpus_recovery_publication.py:89-271` | Sealed batch, completed import, runtime, explicit execute/resume → publication receipt | Pins inputs, holds file lock, reconciles resume, runs guarded phases, writes completion only after final boundary |
| `verify_import` | Same file, 38-63 | Batch/import evidence → completed import | Delegates maintained import-plan verification, including explicit reconciled readiness |
| `verify_coverage` | Same file, 65-69 | Local pair/expected bodies → coverage | Checks exact pair through maintained validator utility; no proof is reused from this coverage-only call |
| `rebuild_retained_catalog` | Same file, 79-85 | Store/staging/root → catalog result | Normalizes body readings before durable internal builder |
| `Store.read`, `Store.put` | Same file, 200-209 | Remote/local catalog body → retained source copy | Source selection and immutable pair materialize for no-op and rebuilt catalogs |
| `Store.put_catalog_manifest`, `validate_pair` | Same file, 193-199,210-214 | Proposed selection → validated conditional selection | Requires imported body coverage and semantic pair validation before selection |
| `Continuation.phase` | `scripts/recovery_publication_continuation.py:56-67` | Named action/output files → accepted result | Hashes accepted artifacts and refuses altered ones on resume |
| `Continuation.record`, `flush` | Same file, 33-42,69-79 | Write event/state → fsynced continuation | Serializes updates with RLock; intent precedes remote write; definite refusals are removed |
| `Continuation.reconcile` | Same file, 98-116 | Persisted intents/current remote objects → resolved state | Resolves committed bytes, preserves original condition for uncommitted requests, rejects conflicts and changed verified versions |
| `Continuation.replay` | Same file, 118-135 | Verified intent/current body → replay receipt or normal write | Requires exact payload and current bytes/version; does not PUT |
| `GuardedPublicationClient.put_object` | `scripts/guarded_recovery_publication_client.py:83-148` | Conditional permitted derived-object write → verified result | Rejects raw writes/unconditional writes, guards, journals intent, performs one PUT and one complete readback |
| `write_lock`, `check_guard` | Same file, 32-46 | Write key/condition → lock/guard mode | Immutable keys overlap; shared commits remain serialized and fresh |
| `upload_file`, `confirm_transfer` | Same file, 54-63,150-160 | Local file/issued proof → current verified transfer | Uses one streamed conditional PUT; forged, foreign, consumed, or stale receipts fail confirmation |
| `upload` viewer | `apps/site/scripts/publish-viewer-r2.py:194-275` | Prepared files/fixed release plan → selected publication | Six payload uploads overlap; complete readback precedes public probes and conditional pointer selection |
| `run` viewer | Same file, 330-364 | Selected catalog/prepared files/optional plan → upload/refresh | Requires prepared source to match current catalog; persisted plan fixes release and timestamp for continuation |
| `validate_catalog_pair` | `packages/congress_api/src/congress_api/retention/catalog_validation.py:51-85` | Exact pair/validator/expected bodies → in-process proof | Two full hashes, schema identity/count checks, coverage, semantic validation, final identity check |
| `CatalogPairValidation.require` | Same file, 39-47 | Proof/current inputs → coverage or refusal | Refuses changed root, manifest, files, validator, or expected imports |
| `verify`, `publish` viewer preparation | `apps/site/scripts/publish-filename-viewer.py:46-53,98-101` | Source pair/optional proof → prepared viewer | Reuses only the maintained proof type; unchanged callers retain standalone checks |

Important callers: dispatcher phase actions call the maintained builder/mapping/viewer modules; viewer upload calls injected `upload_file` and `confirm_transfer`; `R2Store.put_catalog_manifest` calls the injected guarded PUT. No raw capture/state writes are permitted through the publication proxy.

## Data flow and invariants

- The batch/import/runtime/config hashes enter `binding`, persist in `continuation.json`, and are checked on resume. `RecoveryGuard` checks the full pins at phase/shared-write boundaries and notices file identity changes between boundaries (`recovery_guards.py:69-115`).
- Baseline protected ETags cover captures, download state, selected catalog, accepted recoveries, and viewer pointer. Verified writes update only the relevant expected ETag. A stale external change fails a fresh protected check before later shared writes (`dispatch_corpus_recovery_publication.py:147-178`).
- Immutable payloads remain unselected until conditional catalog/viewer pointer updates. Parallel workers can complete an admitted immutable write after another worker fails, but they cannot select those payloads; executor completion occurs before pointer selection (`publish-viewer-r2.py:216-264`).
- An acknowledged or reconciled transfer requires complete response length and SHA-256. Skipping a second full GET requires an issued, exact, one-use proof and a current matching remote ETag/length (`guarded_recovery_publication_client.py:54-63,104-148`).
- T10 proof never persists across restart. A resumed dispatcher reissues it after validating the saved pair. Current expected body coverage remains part of that proof (`dispatch_corpus_recovery_publication.py:192-199,244-247`).

## Tests and edge cases

Executed the five focused publication suites against publication commit `95e429d`: **28 passed, 6 subtests passed**. Temporary artifacts were directed into the acquisition review workspace; no network client was used.

- Dispatcher no-op and failure after each accepted phase: resumes with each phase called once; source files exist before preparation.
- Continuation: changed accepted artifact/binding, uncertain committed/uncommitted request, stale generation, changed verified version, lost acknowledgment, different replay payload, definite immutable locator refusal.
- Guarded viewer: exact one full payload GET even with lost acknowledgment, public payload/pointer probes retained, foreign/forged/stale/consumed proof rejection, six-way immutable overlap, fresh shared guard.
- Catalog pair: two hashes and one semantic validation reused across dispatcher/builder checks; altered bytes with restored mtime, changed root/manifest/expected bodies/validator, missing coverage, and failed semantic validation all reject reuse.

Remaining practical boundary: the full retained-data pipeline and public browser path were not executed. The reviewed implementation and offline checks support local readiness, not a live publication claim.
