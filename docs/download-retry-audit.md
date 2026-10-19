# Download and retry cleanup

Audit baseline: `eaadff05d920441cd4380a0fc719683e28fb764d` (2026-10-19).
Parent ticket: `ct-8w0g`. References below use baseline line numbers.

## Decision

Share three small pieces of existing behavior: synchronous object-storage stream
retries, the Congress.gov JSON downloader, and Senate recording candidate URLs.
Keep source-specific retry rules and validation with their current owners.

The benefit is fewer places to maintain the same decision and clearer ownership.
This work claims no download-speed improvement, lower request count, or production
qualification. It does not change stored data, source selection, retry budgets,
provider fallback, timeouts, or publication authority.

## What goes in, what happens, and what comes out

| Reader | Inputs and work | Output and checks | Decision |
| --- | --- | --- | --- |
| Publisher HTTP | URL, session, permitted statuses; host pacing and selected retries | Response or sanitized transport error | Keep source policy |
| Congress.gov | API key and caller parameters; five-attempt HTTP wrapper | Decoded JSON; parse failures propagate | Move wrapper to transport owner |
| Retained source capture | Admitted URL; bounded bytes, explicit redirects, optional provider | Original bytes, headers, status, completeness and receipts | Keep existing shared reader |
| Object storage | Key and optional version/bounds; SDK request plus body consumption | Checked bytes or files; complete reads authorize later writes | Share synchronous body retry loop |
| Senate audio/captions | Committee and recording name; live then archive candidates | Audio file or retained caption evidence | Share candidate construction only |
| Other media providers | Provider-specific IDs, options and credentials | Provider data, audio, captions or model results | Keep SDK/application policies |

## Evidence and ownership

| Existing source | Relationship and finding |
| --- | --- |
| `packages/congress_api/README.md:191-214` | Authoritative HTTP policy already distinguishes clients; a universal retry client would contradict this design. |
| `packages/congress_api/src/congress_api/transport/http.py:125-192` | Three attempts, 60-second timeout, host spacing, selected statuses, direct House 403 cooldown and secret-safe errors. |
| `packages/congress_api/src/congress_api/acquisition/meetings.py:154-155` and `acquisition/committees.py:11,46,83` | Both collectors use the same Congress.gov wrapper, but committees imports the meeting collector to reach it. Move the wrapper and `API` constant into `transport/congress.py`; retain existing meetings imports. |
| `packages/congress_api/src/congress_api/retention/r2.py:164-197,251-282,290-318` | Three synchronous readers repeat attempt, body-close, streaming-exception and sleep mechanics. Share one private runner inside this module. Each reader retains its own validation and file handling. |
| `packages/congress_api/src/congress_api/transport/audio.py:67` and `transcripts/senate.py:83` | Identical live/archive candidate expressions belong beside the URL builders in `parsers/senate_player.py:58-63`. |
| `packages/congress_api/src/congress_api/transport/rust_fetch.py:103-115,234-282` | Native transfer already adapts to `fetch_source`; fallback and file ownership are centralized. Another transport layer would duplicate that boundary. |
| `packages/congress_api/pyproject.toml:60-62` | Retention cannot import transport. Keep the storage retry helper in retention. |

## Rules the refactor must preserve

- SDK `get_object` failures stay outside body-stream retry handling. Retry only
  the existing streaming exception classes with the existing attempt budget,
  log fields and jitter. Close each response before sleeping.
- Byte reads may receive a different object version on retry. Update
  `index_etags` only after a complete read; missing indexes clear that value.
  File readers instead pin the first ETag, send `IfMatch`, and reject changed
  versions. A missing derived object is absent only before a version is pinned.
- Body-file reads truncate caller-owned scratch files. Derived-table reads use
  `copy_checked`, retain failed partials, verify bytes/hash, and publish only
  complete files (`retention/derived_files.py:112-153`). Do not combine the sinks.
- Integrity, size, filesystem and SDK failures remain failures, not new retries.
  Async storage keeps asynchronous closure/sleep and its additional
  `ClientPayloadError` handling (`retention/r2.py:128-145`).
- Congress.gov retains five attempts by default, explicit overrides, API-key
  and format precedence, unchanged caller parameter mappings and JSON errors.
- Senate candidates stay live-first, then archive, or archive-only when no live
  mapping exists. Audio and captions keep their different validation, fallback,
  caches, receipts and failure meanings.
- House XML parsing retries remain separate from HTTP retries. The first request
  permits 404; later parse retries require 200. Bad XML stays `invalid_xml`
  (`acquisition/house.py:83-105`).
- Senate captions retain three immediate attempts, pool size 32, 30-second
  timeout, empty-200 retries and captured 404 absence (`transport/senate.py:17-47`).
  Direct GPO/YouTube/urllib calls and Gemini/yt-dlp SDK behavior remain separate
  (`transcripts/generate.py:68-75,108-121`, `transcripts/context.py:53-56`,
  `transport/gemini.py:94-139`).
- Full source capture treats 206 as incomplete; range recovery requires pinned
  exact 206 ranges and a durable journal. Prefix probes intentionally stop early
  and do not claim a complete archived document (`transport/source_capture.py:115-117,152-154`,
  `acquisition/streamed_recovery.py:41-118`, `transport/document_probe.py:23-41`).
- Source Retry-After handling preserves raw duplicate fields and long deferred
  waits; R2 throttling refuses waits over one minute. Preserve those differences
  (`transport/rust_fetch.py:22-65`, `retention/r2.py:37-81`).

## Tickets and local checks

`ct-yxup` records this audit. After it closes, these independent tickets can run
in parallel: `ct-84x7` (storage), `ct-xh2t` (Congress.gov), `ct-677t` (Senate URLs).
`ct-kpuy` depends on all three and owns combined local verification and cleanup.
The parent `ct-8w0g` depends on that final task.

Storage checks cover stream interruption, close-before-sleep, exhaustion,
missing/changed versions, bounds, partial files and conditional-write state.
Congress.gov checks cover exact parameters, attempt override, JSON failure and
both collectors. Senate checks cover exact candidate order, archive-only
recordings, fallback, cached files and retained caption evidence. Existing
HTTP-policy and import-fence tests guard intentional differences. Run the
maintained `production-offline` suite once on the integrated code, plus independent
review of each exact change. Local checks are the merge gate; do not wait for CI.

## Alternatives and review verdict

**Keep** the existing shared capture and HTTP gateway. **Reshape** only the three
ownership/duplication points above. A universal retry engine would require flags
for different absence meanings, delays, byte bounds and evidence handling; it
would add coupling without changing a user outcome. A shared thread-local session
allocator saves too little to justify another dependency. Common yt-dlp options
and the repeated provider byte-limit expression are smaller optional cleanups;
leave them out of this change.

**APPROVE this scope.** It preserves the documented boundaries and reduces
maintenance duplication. Reject any implementation that needs broad policy flags,
changes request counts or delays, loses failure evidence, or moves storage above
transport. The value claim fails if a future fix still requires editing multiple
copies of the same extracted decision. Exact implementation review and local
tests remain required; the audit alone does not qualify a patch.
