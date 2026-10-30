# Congress MCP production acceptance, 2026-10-30

## Measurement plan

The fixed input is the complete deployed phase 2 release
`a06e2a636d3c765f81be13712f496aa25a0dec50d7055ea8a1dbb18f0ebf1e25`:
16 Parquet tables, 367,008 documents, 1,201,754 URL-state rows, 18,687 meetings,
56,066 witness appearances, 11,832 bills and 747 nominations. The metadata-only
successor must retain every Parquet digest and row count.

Use the actual stdio client and server with the app's locked environment. Measure
one startup and three warm repetitions of representative document/entity searches,
document lookup, published recipes, and a four-request concurrent batch. Sample
the simultaneous RSS of the server and all its descendants every 50 ms; report
sampling limitations and host details. Do not treat the 512 MiB DuckDB setting as
a bound on process RSS. Record response bytes and query outcomes as well as time.

The decision rule is functional completion within the existing 10-second query
deadline and 128 KiB response bound, without worker loss or leaked work. Report
observed latency and memory rather than inventing a hardware-independent SLA.
One warm workload is enough unless a failure or a subsequent change requires
another run. Stop on timeout or memory pressure and fix the responsible path.

Preparation reuses the verified local objects for measurements. Fresh public
preparation after publication checks the remote-to-consumer boundary once.
No document bodies or full raw-corpus rebuilds are needed.

## Public metadata result

Published release:
`0db23484fe86c7f5a5e50e44f078ec34e74e793873b26c4a15f0b9e9efa17b69`.
Only `schema.json` changed. Every Parquet digest, byte count, row count and
original model/provenance association remains the same. The new input record
explicitly identifies this as a metadata update of the previous release; it does
not claim that the current model rebuilt the underlying data.

The producer registry generated the new metadata. Footer validation confirmed
the reference field types. The qualified native engine evaluated all 13 new
relationship diagnostics against retained phase 2 outputs: every count was zero.
The earlier native export and admission results remain the evidence for the
unchanged data. The original comparison acceptance was revalidated.

The maintained publisher uploaded the candidate using create-only writes, passed
the actual built-site desktop/phone/stale-tab checks and the HTTPS canary, then
changed the pointer conditionally against its observed ETag. Publication took
56.69 seconds, including 18.47 seconds uploading 68,173,793 asset bytes. The HTTPS
canary also fetched an actual saved file. These are publication checks, separate
from MCP performance measurements.

A final lifecycle check caught that retained-input validation did not yet accept
the new metadata-update marker. The canonical profile builder now validates its
base release, registry/schema SHA-256 values and relationship version explicitly.
The actual published input record was read back over HTTPS and passed retained-
input validation with all 2,292 original receipt keys. No immutable record was
rewritten. Sixty focused profile/retention tests pass; malformed markers still
refuse deletion. The same tests now run in the native-consumer CI job. See
[`congress-mcp-retention-20261030.json`](congress-mcp-retention-20261030.json).

A fresh public `prepare` selected this exact release and verified all 16 tables.
Actual stdio discovery returned all table identities and 59 relationship
definitions. The receipt summary is in
[`congress-mcp-publication-20261030.json`](congress-mcp-publication-20261030.json).

## Integration and regression checks

The dedicated CI lane now builds the existing native phase 2 producer fixture
and hands its actual release to the independent DuckDB 2 MCP environment. The
stdio check discovers the six tools, traverses the published tables and
relationships, executes the ten recipes and checks entity/document navigation.
It uses the two existing project runners and locks. It does not duplicate the
producer fixture or install DuckDB 2 into the producer environment.

The producer's semantic file hashes now include `archive_schema.py`, as well as
the existing schema registry. A change to metadata-building or relationship-check
code therefore invalidates publication reuse, even when the registry is unchanged.

The first broad regression run found two cases of one stale XML-recovery test:
it expected an API key in query parameters after the implementation had moved
the key to `X-Api-Key`. The expectation now verifies the header and still checks
that saved source records contain no key. All 17 XML-recovery tests pass locally.

## Complete-release MCP measurements

The actual stdio workload passed with the original 10-second query deadline and
128 KiB data-response limit. Host: Mac16,8, 14 CPU cores, 48 GiB RAM, macOS 26.6,
Python 3.12.13. Each warm measurement has three repetitions.

| Operation | Observed result |
| --- | ---: |
| Process launch through first dataset discovery | 1.26 s |
| Document metadata search, 25 results | 57 ms median |
| Witness name search, 25 results | 38 ms median |
| Document detail | 33 ms median |
| Document count by Congress | 14 ms median |
| Ten published recipes | 8–32 ms median each |
| Four simultaneous requests, entire batch | 124 ms median; 141 ms maximum |
| Simultaneous server/worker/support-process RSS | 322.5 MiB sampled peak |

All 16 table identities and 59 relationship definitions were inspected. All ten
recipes executed; this does not assert that every chosen identifier has data for
every relationship. Positive results included bill/hearing/witness documents,
committee rosters and bill/nomination votes. The selected witness/nomination
transcripts, recording tracks and document editions returned zero rows. A
separate parameter-selection query found no non-null witness `package_id` in
this release. That is a producer data-coverage gap, not a missing MCP table.

RSS samples include all three server-side processes and exclude the measurement
client and `ps` sampler. The target sampling delay was 50 ms; process inspection
added overhead, with a maximum observed interval of 137 ms. Shorter peaks can
be missed. This is a local warm-cache observation, not a process memory limit or
a hardware-independent performance guarantee.

An initial bill-ID query hit the 10-second deadline. It did not recur in direct
DuckDB, Reader, spawned-worker, stdio-with-sampler checks, or the complete final
workload. Its cause remains unknown; no deadline increase or speculative query
change was made. The failed measurement log is retained locally. Timeout/retry
and worker cleanup remain covered by the recovery tests.

Reproduce against an already prepared public cache:

```sh
apps/explorer_mcp/.venv/bin/python docs/measurements/measure_congress_mcp.py \
  --data-dir /absolute/path/to/mcp-cache \
  --output /absolute/path/to/measurement.json
```

The committed result is
[`congress-mcp-production-20261030.json`](congress-mcp-production-20261030.json).

## Recovery result

All **55 MCP tests** passed locally, including the fresh native-producer stdio
check and ten recovery cases. The worker watches the standard multiprocessing
parent-death signal, interrupts DuckDB and closes it before deleting its own
scratch. A bounded forced-exit fallback prevents an orphan query from running
indefinitely. Unexpected worker disconnection returns an actionable error and
the next request starts a fresh worker.

Preparation now removes its named incomplete download/selection files only
while holding the exclusive prepare lock. Actual SIGKILL during a partial write
preserved the previous selection; the next preparation completed and retained
the old reader's immutable objects. Injected ENOSPC at payload and selection
writes, reset/truncated transfers, update/rollback, and corrupt-old-object
refusal also passed. Completed objects are retained for active readers; cache
retirement remains an explicit stop-all-readers then remove-cache operation.

The full public-release update/rollback check also passed through two concurrent
stdio servers. Updating the prior release took 0.94 seconds, reused all 19
existing objects unchanged and added only the new schema object. The old server
kept the prior release; the new server kept the updated release even after the
cache selection rolled back. Both still counted 367,008 documents. The final
selection was restored to the public release. See
[`congress-mcp-update-rollback-20261030.json`](congress-mcp-update-rollback-20261030.json).

## Committed CI

Code commit: `c649abece2a5b802a1381e6fb61a2feb5f3bd4fa`, merged and pushed to main.
[MCP CI passed](https://github.com/civictechdc/congressional-tech/actions/runs/41082729727),
including both the isolated app suite and native producer-to-stdio job.
[The broader repository run](https://github.com/civictechdc/congressional-tech/actions/runs/41082733637)
is still in progress; final disposition will be recorded here.
