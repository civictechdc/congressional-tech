# Browser remediation checks

These checks use controlled fixtures. They do not establish full-catalog browser memory, throughput, or deployed behavior.

The later actual-catalog parsed-metadata reuse failure and its separate reader
correction are recorded in [browser-metadata-reuse.md](browser-metadata-reuse.md).
The correction preserves cache limits and the independently accepted backend
preparation result.

## Reader lifecycle and input rules

The browser owns pending request cleanup in `filename-client.mjs`. Error, cancellation, failed structured clone, and result paths each remove the abort listener and pending entry once. Worker errors terminate that worker; a later request creates a fresh reader with the same pinned catalog. Initial information failures keep the existing Reload action.

A persisted `pagehide` releases the publication watcher and aborts its in-flight freshness request. `pageshow` starts one watcher for the same catalog identity. Permanent unload disposes it. The UI ignores history notifications while information is pending and restores the latest URL after readiness.

Page and limit input use positive finite numbers, rounded down and clamped to the known maximum. Invalid, infinite, zero, and negative input use the boundary's default (page 1, search limit 50). The local Python reader follows the same rule. A filename date displays as a calendar date only when its UTC round trip exactly matches the literal date; impossible dates remain literal.

Focused verification: client failure/retry/cancel/throw cases, watcher suspension/restoration and in-flight abort, latest pending-info history, actual worker API routes with generated Parquet fixtures, and the existing complete UI tests. The worker fixture confirms deferred detail, paged observations and full-record fidelity.

## Optional review startup

`loadReviews` accepts a configurable policy with a 15-second total deadline and a 16 MiB maximum per JSON input. Both the binding and review publication must declare an expected byte count within policy. The reader rejects an inconsistent identity Content-Length when visible and stops stream consumption at the first byte beyond the expected count. Actual bytes, SHA-256 and catalog/pair checks remain the acceptance authority. A deadline race settles startup even when a fetch implementation ignores AbortSignal.

Optional review failure leaves the original catalog available and explains why reviewed search is unavailable. Recoveries retain their independent fail-closed policy: corrupt length, digest, catalog identity or positions reject initialization. Missing recoveries remain valid. The tests exercise these distinctions directly.

## Shared retained-byte caches

One immutable reader owns a 48 MiB compressed range cache and a 64 MiB decoded-value cache by default. All Parquet/navigation/observation ranges share the compressed budget; table metadata, normalized source columns and observation-store descriptors share the decoded budget. Entries include a fixed/key bookkeeping allowance. Value accounting uses UTF-16 string lengths, typed-buffer lengths and explicit array/object estimates; this is a conservative accounting model, not an engine-specific heap profiler. Fixed global navigation arrays, active decoder output, cloned worker results and clipboard strings remain separate necessary/transient costs.

Concurrent first loads share range, table, column and observation-store promises. A caller's abort only stops that caller's wait. Shared failures evict and retry. A monotonic row-group cursor replaces queue shifting. A value larger than the cache budget is returned exactly but not retained, so the next request takes the full-scan fallback.

A seven-source wide-column fixture (5,000 repeats of Unicode text per field) produced one column load for concurrent and repeated searches. Cold range work was 2 requests / 22,752 bytes; the repeated query added no transfer or column decode. Estimated retained decoded state was 906,686 bytes. With a 64 KiB decoded budget, the wide values were not admitted (0 retained bytes), the second search decoded the column again, and results remained identical. The compressed peak was 23,612 bytes including entry accounting, below the fixture's 128 KiB budget. Sixteen cache/catalog checks passed. These controlled costs do not predict full-catalog performance.

## Range and sparse selection work

Mutable pointer reads keep `no-store`; immutable catalog locators and release manifests use `force-cache` after checking their catalog identities. Source-ID prefix shards use the shared decoded-byte cache. The same-prefix fixture resolves two different IDs with one shard request.

Prefetch occurs only when all planned merged ranges fit admission; otherwise the maintained Parquet reader fetches its own chunks. The oversized-prefetch fixture makes exactly the same 2 range requests / 11,187 bytes as explicitly disabling prefetch. Sparse selection groups positions by row group and consumes the maintained reader's column callback, creating and normalizing only selected row objects. It does not avoid physical column decoding: the controlled two-row selection visits 138 physical column values and normalizes 46 selected browse values. Two separated rows span four rows in that fixture, so the earlier broad-span object path would normalize 92 browse values. Existing modern-versus-archived navigation equivalence tests remain green; modern initial details avoid global legacy navigation arrays and archival Parquet.

## Cooperative cancellation

Scalar and group scans yield to the worker message queue every 512 visited rows. Observation and source-reference scans count work across blocks and within long reference lists, so small blocks do not introduce a timer per row. Each yield checks cancellation before and after returning to the queue. A single synchronous JSON parse/stringify or Parquet/Brotli decode remains an indivisible operation; the logical-decode accounting below describes that limit.

On a 4,096-source fixture, direct canceled scalar/group scans completed at most 512 visits before abort (observed 0.6–1.9 ms). Separate actual-worker tests warm each route, cancel scalar, group and observation searches by worker message, then issue `/api/info`; observed response latency was 0.14–3.9 ms and canceled results stayed suppressed. The fixture records uncanceled cold-scan elapsed time separately; these are latency/work observations, not full-catalog throughput claims. Seventeen catalog/worker checks passed.

## Search normalization and page accumulation

Search keeps at most two page-sized group lists: the requested page and the current final page. Counts and ordering come from the unchanged full scan; an oversized page request selects the final page after counting. It no longer stores every matching group. Arbitrary-field and same-source filter semantics remain intact, including review overrides and withdrawal behavior.

Optional scalar/observation text representations share the decoded cache. Each representation admits at most 8 MiB and at most one quarter of the configured decoded budget; larger inputs use the exact per-value full scan. Normalization can stop at the admission threshold and fall back, so a cold oversized search can repeat a bounded prefix of formatting work. No specialized common-field index was added: it would add a second query path and build cost while arbitrary fields still require the reference full scan. The measured representation already removes repeated formatting without changing matching logic.

A controlled repeated filename query performed 14 cold normalizations and zero additional warm normalizations, with 2 cold column loads and 2 range requests / 22,717 bytes unchanged on repeat. The original observation fixture performed 2 unique-observation normalizations and zero additional warm normalizations. With normalization disabled, repeated queries still return the same values and perform the expected formatting again. A one-result page retains at most 2 group IDs rather than all 6 matches. The expanded Python-reference fixtures cover same-source AND, Unicode and nested JSON keys; existing reviewed/null/recovered/duplicate/order checks remain green. Eighteen catalog/worker checks passed. The 4,096-source cold scan observed 38 ms separately from cancellation latency; fixture results do not establish full-catalog throughput.

## Logical decode and complete-copy memory

The ordinary logical-decode accounting threshold is 16 MiB of serialized UTF-8, separate from retained-cache budgets. It classifies oversized work; it does not reject or shorten exact values. The current JSON format requires a complete logical text and parsed value. Values above the threshold still use the exact route and are not cached when they exceed retained admission. If the engine raises an allocation `RangeError`, the reader reports an explicit browser-memory error and directs the user to the source Parquet download. A hard browser limit would require a new incremental/value-addressable format or a deliberate download-only policy; this change adopts neither implicitly.

The decoder now uses streaming UTF-8 across Brotli parts, preserving split code points while releasing each decoded byte part. It eliminates both the retained decoded-parts array and the joined whole-logical-block byte buffer. It yields between four parts. Parsed observation/reference blocks may reuse the shared decoded cache, with shared concurrent loads and exact uncached fallback. Normal source details continue to defer observations; complete-copy requests remain explicit.

A value of 1,680,021 serialized UTF-8 bytes used parts of at most 65,537 bytes, with zero joined decoded-byte allocation. The logical text was 2,160,042 UTF-16 bytes and the parsed-value estimate was 2,160,154 bytes. With a 1 MiB cache the oversized parsed value was not retained; only 160,314 bytes of reference data fit. A 10,000-reference list, null list, duplicate observation references and split Unicode all preserved exact order/values.

Memory categories remain distinct:

| Category | Accounted cost / boundary |
| --- | --- |
| Compressed ranges | Shared retained cache; fetched ArrayBuffer can also be transient while admission is decided. |
| Decoded bytes | One part at a time, at most the declared 1 MiB part cap; whole-block joined bytes eliminated. |
| Logical JSON text | Complete UTF-16 string remains necessary for `JSON.parse`; engine string/rope overhead is not a measured heap bound. |
| Parsed objects and restored values | Explicit retained-value estimate; cache admission is separate from active exact results. |
| Scalar/full result | Separate per-reader maximum value estimates; source field order and duplicates preserved. |
| Worker clone | Structured-clone graph adds a separate main-thread result; fixture estimate 2,160,200 bytes, preserving duplicate object references. |
| JSON formatting | Complete-copy fixture produces 4,320,132 UTF-16 bytes (3,360,066 UTF-8 bytes), including repeated values as required by JSON. |
| Clipboard | `writeText` receives the full formatted string; browser/OS may allocate another copy. Its internal allocation is not exposed by the API. |

These estimates are separate simultaneous costs, not an overall browser-memory ceiling. Nineteen catalog/worker checks passed, including the large logical value and actual worker routes. Full-record formatting/clipboard errors continue to show an explicit copy failure while keeping the selected detail usable.

## Explicit page and adapter boundaries

The shared markup is `filename-viewer-body.html` and shared styling is `filename-viewer.css`. Astro imports both directly. The local shell has one named body marker, which the localhost handler requires and replaces with that same fragment. The local handler serves an explicit module/style allowlist. Runtime rendering no longer extracts HTML with delimiter regexes.

`filename-adapter.mjs` selects an explicit published or local mode. Published requests require the worker, reviewed evidence requires published links, saved files require valid HTTP(S) URLs, and local naming comparisons are ignored. Missing worker/evidence data produces a visible error; it cannot fall back to local `/api` or `/review-evidence` HTTP requests. Local mode preserves saved-file/evidence routes, API errors and current-versus-published naming comparison, including raw differences and version caveats.

The local HTTP integration serves the composed page and every imported module/style; the Python viewer suite passed 41 checks, including adversarial pagination. Adapter/markup/public-mode UI checks passed. The emitted Pages bootstrap runs both ordinary and pinned-source scenarios under `/congressional-tech/`, preserving the requested immutable catalog and avoiding eager full/evidence reads. The local pinned archive and all review evidence verified before the 29-page build. No Explorer publication or remote deployment is implied by this local build.

Runtime verification used explicit Node 22.21.1 and npm 11.19.1 for a frozen install, 144 maintained JavaScript checks, 29-page build and two emitted-bootstrap checks. That install exposed an engine metadata mismatch: locked jsdom and dependencies require Node 22.22.2 or newer within Node 22. Root is updating the declared runtime; this receipt is execution evidence under the older runtime, not a supported-runtime claim. The new public-mode and compressed-response checks pass separately; the final supported-runtime receipt will supersede this paragraph.

HTTP review admission also distinguishes transport bytes from decoded bytes: gzip/Brotli Content-Length can describe compressed transfer, and CORS may hide the encoding header. Only a visible identity, non-CORS response uses its Content-Length as an early consistency check. The streaming cap, exact decoded length and digest validate every response, including encoded/CORS responses.

## Final supported-runtime receipt

The final engine-strict frozen install passed under **Node 22.22.2 / npm 11.19.1** with no engine incompatibility. The lockfile remained SHA-256 `ef5529088d88e2b34298a2136f801cecfff88e2f39e5261202c92b4cb740ef27`. This supersedes the earlier Node 22.21.1 execution receipt.

All **146 maintained JavaScript checks**, **41 Python viewer checks**, the **29-page Astro build**, and **2 actual emitted-bootstrap scenarios** passed. An additional **19 catalog/worker checks** passed with explicit worktree Python package paths, confirming current worktree implementations rather than depending on editable package routing. The pinned local review archive passed complete verification before build. `evidence/browser-final.json` records the tested code revision, runtime, lock identity, checks and emitted filename bundle digests. No remote workflow or production writer was started.
