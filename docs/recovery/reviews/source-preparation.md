# Current review result

**VERDICT: APPROVE for local implementation through integration `ee728cf`.** The original transport-timestamp blocker is resolved by `4df6554`, and `ee728cf` preserves declared sealed hashes across later reads. The final focused execution passed **24 source-preparation tests**; the combined source-preparation/dispatcher run passed **33 tests and 5 interruption subtests**. No remaining blocker was found. This is local offline evidence, not an import or publication claim.

The original certificate below is retained as historical evidence for `edd6704`. The final rereview after it supersedes that initial verdict.

---

# Independent review: maintained source-record preparation

**VERDICT: REQUEST CHANGES at integration commit `edd6704`.** One provenance blocker remains: transport timestamp fallback is not bound to the recovery's URL and body. The output layout, sealed-manifest preservation, and absent-only publication are otherwise consistent with the maintained consumers.

Scope: `scripts/prepare_corpus_recovery_source_records.py` and `tests/test_prepare_corpus_recovery_source_records.py`, added by `edd6704` (publication-tree source commit `d7230fe`). This certificate records the reviewed commit; a later correction needs a focused rereview. No implementation files were edited.

## Findings

### F1 — BLOCKER: an unrelated transport receipt can supply a source timestamp

Category: correctness. Location: `scripts/prepare_corpus_recovery_source_records.py:93-113`.

When a source time is missing, `prepare` reads `request_evidence` and accepts only its `record.retrieved_at` field. It does not check the transport record's URL, SHA-256, length, completeness, or rendered-copy provenance. It then creates a new response describing the sealed row's source and bytes with that unrelated time (`prepare_corpus_recovery_source_records.py:117-129`). A valid body hash only proves the local body matches the sealed recovery; it does not connect the timestamp receipt to that body.

Concrete trace: a validated sealed recovery for URL A/body A can point to a receipt for URL B/body B with a valid timezone-bearing timestamp. The command records A/body A at B's time and reports no unresolved timestamp. The existing transport probe supplies just `record.retrieved_at` and succeeds, demonstrating that no identity binding is required (`tests/test_prepare_corpus_recovery_source_records.py:99-105`). Downstream `assemble` checks capture/body/source consistency against this newly generated record, so it cannot discover the incorrect timestamp lineage (`scripts/assemble_corpus_recovery_import.py:48-75,90-99`).

Required correction: accept a documented receipt shape only when it binds the exact approved source URL and sealed body SHA-256/length. A rendered fallback must also prove rendered-copy provenance. Reject mismatches before either output; preserve the source evidence hash. Existing dated qualification receipts use `record.final_url`, `record.sha256`, `record.bytes`, and `record.retrieved_at`; raw archive receipts use `record.url`, `record.content.sha256`, and matching `captures[]` body metadata. Do not assume raw `record.content` contains a byte count.

### Observation: bounded offline evidence

The nine tests pass, but they do not currently exercise transport URL/body mismatches, rendered transport fallback, or an actual preparation → reconciliation → assembly round trip. The unbound transport success fixture must become a refusal fixture or a fully identified receipt. Existing timezone, byte identity, output refusal, and report-last failure assertions are meaningful for their stated paths.

## Patch summary and exploration

The command adds missing prepared records and a completion report to a sealed batch. It verifies manifest-listed files, hashes the captures table and optional aliases, verifies every local body's SHA-256/length/content-addressed key, chooses an explicit source time, uses maintained `raw_archive.prepare_capture`, then adds the two completed outputs without overwriting existing paths (`prepare_corpus_recovery_source_records.py:45-154`). Its only direct caller found is the CLI entry point (`:157-163`).

H1: preparation rewrites sealed inputs. Refuted by the write trace: all writes target a temporary directory and the two missing outputs; the manifest is read/hashed and never written (`:55-63,134-153`). The manifest-preservation test also compares its bytes before and after (`test_prepare_corpus_recovery_source_records.py:44-52`).

H2: rendered HTML may inherit an older archive snapshot timestamp. Refuted for the explicit sealed-row-time path: rendered rows take their own aware `retrieved_at`, retain the original candidate timestamp in acquisition evidence, and set `original_archive_response_bytes=False` (`prepare_corpus_recovery_source_records.py:90-105,118-128`). Refined for transport fallback: the intended separation exists, but F1 allows an unrelated or nonrendered receipt to supply the render time.

H3: a partial output can silently become a completed pair on retry. Refuted: either existing output causes an immediate refusal, each output appears only after its staged file is complete/fsynced, and the report is linked last (`:47-49,142-153`). The injected second-link failure leaves a diagnosed partial pair whose first file is preserved (`test_prepare_corpus_recovery_source_records.py:115-128`).

## Function trace

| Function | Location | Input → output | Verified behavior |
| --- | --- | --- | --- |
| `digest` | `prepare_corpus_recovery_source_records.py:31-33` | File → SHA-256 | Streams the file through `hashlib.file_digest` |
| `instant` | Same file, 36-42 | Candidate timestamp → aware datetime or `None` | Rejects missing, malformed, and timezone-free values; supports UTC `Z` |
| `prepare` | Same file, 45-154 | Batch, captures table, optional aliases → prepared records/report | Verifies sealed files and local bodies; derives records; publishes absent-only outputs |
| Nested `read` | Same file, 51-54 | JSON evidence path → value plus input hash | Hashes and parses the same bytes; records resolved source path |
| CLI | Same file, 157-163 | Explicit paths → `prepare` report | No implicit queue, runtime output, network, or timestamp defaults |
| `CapturedBody.from_bytes`, `source_dict` | `packages/congress_api/src/congress_api/models/content.py:31-37` | Verified bytes/type → source content | Computes byte identity using maintained representation |
| `raw_archive.prepare_capture` | `packages/congress_api/src/congress_api/retention/raw_archive.py:106-124` | Source response → record, captures, body map | Separates content without storage writes; caller checks exact one-body identity |
| `sealed_inputs` consumer | `scripts/reconcile_corpus_recovery_bodies.py:90-111` | Batch plus new outputs → verified inventory/counts | Adds preparation hashes, requires complete report and matching manifest, checks capture coverage/identity |
| `verify_batch` consumer | `scripts/dispatch_corpus_recovery_import.py:32-48` | Batch/readiness → pinned files | Requires report completion and sealed-manifest identity |
| `assemble` consumer | `scripts/assemble_corpus_recovery_import.py:42-86` | Prepared records/current state/verified bodies → receipts | Preserves existing download state; validates source association, body identity, context and pointer |

## Data flow and invariants

- `manifest` enters from sealed JSON at line55. Every listed file is checked against its expected hash at56-59. `recoveries.json` must be listed at60-61. The report carries the manifest hash at134-136.
- `prior` receives only requested `(recovered_url, body_key)` capture matches at64-72. Aware datetime comparison chooses the latest actual instant, including differing UTC offsets. Optional explicit aliases match body and package basename at73-79; they fill a missing match rather than replacing an exact capture match.
- Body bytes enter from `body_path` at84-85. SHA-256, logical content-addressed key, and byte count must all agree at86-88. The maintained capture result must describe exactly that single body at129-131. Only metadata/local paths escape in the prepared output.
- `at` comes from a sealed rendered row, archive-index snapshot, exact retained capture, or transport receipt at90-113. Missing/invalid time creates an unresolved item at114-116; the command never substitutes the current clock. F1 identifies the missing transport identity check.
- Rendered source evidence retains the original acquisition row and marks the response as rendered without asserting original archive bytes at118-128. Nonrendered snapshot time remains a UTC archive capture time at102-105.
- Output values become complete staged files at142-146. Hard links publish without replacement, prepared records first and report last, with directory fsync after each link at149-153. An interrupted pair requires explicit diagnosis; the command never fills an existing pair automatically.

## Tests and concrete edge cases

Executed the added test file against integration `edd6704`: **9 passed**. This was an offline local test run; no live writes or primary-checkout changes occurred.

| Test | Location | Result and trace |
| --- | --- | --- |
| Exact URL/body chooses latest documented capture | `test_prepare_corpus_recovery_source_records.py:37-52` | Passes; excludes wrong URL/body and chooses later instant across offsets; checks manifest preservation |
| Alias requires exact body/package basename | Same file,55-66 | Passes; rejects wrong body/package and handles query/uppercase suffix while preserving alias hash |
| Direct archive snapshot semantics | Same file,69-76 | Passes; emits parsed UTC snapshot time and does not need unrelated transport evidence |
| Rendered copy keeps render time/snapshot provenance | Same file,79-88 | Passes; preserves actual sealed render time and old candidate timestamp separately |
| Missing timestamp never uses now | Same file,91-96 | Passes; emits no capture and a concrete unresolved reason |
| Transport time/evidence hash | Same file,99-105 | Passes but exposes F1; receipt identity fields are absent and accepted |
| Changed body refusal | Same file,108-112 | Passes; no output is created after byte identity failure |
| Existing/partial output preservation | Same file,115-128 | Passes; second-link failure leaves first output, retry refuses and preserves it |
| Changed sealed recovery rows | Same file,131-134 | Passes; manifest mismatch stops preparation |

Remaining unsupported condition is deliberate: a pre-existing partial preparation is refused, not automatically resumed. A malformed candidate snapshot timestamp remains unresolved rather than being replaced with today's time. Neither behavior weakens downstream import checks.

## Conclusion

VERDICT: REQUEST CHANGES

- The addition preserves sealed inputs, writes absent-only completed artifacts, and produces the downstream record shape.
- Transport timestamp lineage is not established by current checks, so it does not yet achieve its stated provenance intent.
- Coverage of changed paths: INSUFFICIENT for transport identity and rendered transport fallback; adequate for the other enumerated paths.
- Confidence: HIGH for F1 and the traced local behavior. No production import or publication was performed.

## Final rereview at `ee728cf`

Reviewed corrections `4df6554` (publication source `eac2ed6`) and `ee728cf` (source `631111e`) against the original addition. No implementation source was changed during review.

### Resolved findings

**F1 RESOLVED.** `transport_time` now accepts two explicit receipt shapes and refuses a mismatch before output publication (`scripts/prepare_corpus_recovery_source_records.py:45-74`):

- A dated qualification receipt must have exact `record.final_url`, body SHA-256, integer byte count, explicit completeness, and successful integer HTTP status (`:49-64`).
- A raw archive receipt must have exact `record.url`/content SHA-256 plus exactly one matching publisher-body capture with the approved context URL, body key, SHA-256, and integer length (`:52-64`). The capture and record must identify the same aware timestamp (`:65-70`).
- Both paths require a timezone-bearing record time before acceptance. A missing or invalid time remains unresolved. A rendered fallback additionally requires explicit `rendered_copy=True` on the record or receipt (`:65-74`).

The caller invokes this binding helper for rendered fallback and ordinary transport fallback (`:130-148`). A rendered row's own sealed acquisition time remains usable, while the original archive timestamp stays in acquisition evidence and `original_archive_response_bytes=False` remains explicit (`:131-136,153-163`). The correction does not substitute archive snapshot time for rendered bytes.

**Declared input hash race RESOLVED.** Nested `read` compares the newly read bytes against any earlier declared hash before retaining them (`:83-89`). The sealed recovery hash is installed at91-94 and cannot be silently replaced by a changed JSON read at97. Final input rechecking remains at174-176. The new injected-mutation test demonstrates refusal before either output (`tests/test_prepare_corpus_recovery_source_records.py:212-223`).

### Updated function and consumer trace

| Function | Current location | Inputs and output | Review conclusion |
| --- | --- | --- | --- |
| `transport_time` | `prepare_corpus_recovery_source_records.py:45-74` | Sealed row + identified receipt → source time or refusal | Exact URL/body/length/status/completeness; raw capture time equivalence; rendered marker required |
| `prepare` / nested `read` | Same file,77-189 /83-89 | Sealed batch/captures/aliases → prepared records/report | Retains manifest assertions across rereads, verifies body identity, uses bound fallback, rechecks inputs |
| `prepare_capture` call and output checks | Same file,158-168 | Verified response/body → one prepared capture | Existing downstream-compatible response/record/capture/body-map shape is preserved |
| Atomic publication | Same file,177-188 | Two fsynced staged JSON files → absent output paths | Hard links cannot replace existing paths; report remains last |
| Maintained consumers | `reconcile_corpus_recovery_bodies.py:90-111`; `assemble_corpus_recovery_import.py:42-99` | Prepared outputs → readiness/import receipts | Body inventory, pointer, source association, and preserved-state expectations remain satisfied by the prepared shape |

### Final tests and edge cases

The 24 source-preparation cases pass offline. The existing nine paths retain their prior assertions. Added cases now reject wrong qualification URL, SHA-256, byte count, boolean byte count, incompleteness, and unsuccessful status (`test_prepare_corpus_recovery_source_records.py:139-152`). Raw receipt success establishes the actual record/content/capture shape and pins its evidence hash (`:155-169`). Raw capture URL, key, SHA-256, length, and time mismatches all reject before outputs (`:172-183`). Rendered fallback fails without a rendered marker and succeeds with one (`:186-197`). Missing bound time remains unresolved (`:201-208`). The sealed-read mutation case refuses before outputs (`:212-223`).

No new blocker emerged from mismatched receipt shapes or downstream review. The tests do not run a full production preparation/import/publication sequence; the scope is this local command and its maintained data shape.

VERDICT: APPROVE

- The corrected addition preserves sealed inputs and exact source/body/timestamp lineage while producing the maintained downstream record shape.
- Coverage of changed paths: ADEQUATE for this local command.
- Confidence: HIGH. No live import, remote write, or publication was performed.
