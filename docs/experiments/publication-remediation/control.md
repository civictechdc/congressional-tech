# Publication control measurements

`evidence/control-costs.json` retains a bounded generated fixture run. It separates
accepted preparation, successful publication, unchanged poll, a deliberately failed
explicit resume, and the next explicitly invoked resume. The failure and its local
journal remain in `/tmp/publication-control-cost-run-telemetry/attempt`; the durable
receipt includes failure type and exact input/runtime/measurement source pins.
No cloud request or production mutation occurs. The full Linux catalog OOM stage
remains unknown; this run does not retry it or change its resource limits.

Reproduce against any pinned local checkout with the same Python runtime and one
unchanged source directory. Generate the small fixture once, then reuse it for all
arms. A fresh process imports the selected checkout's maintained publisher and
attempt code plus its retained mock Remote/custody test adapter:

```sh
PYTHONPATH=apps/site/scripts:scripts:packages/congress_api/src /Users/mikewolfd/Work/congressional-tech/.venv/bin/python apps/site/scripts/filename-test-fixture.py /tmp/publication-control-cost-fixture
PYTHONPATH=scripts /Users/mikewolfd/Work/congressional-tech/.venv/bin/python scripts/measure_publication_control.py --checkout CHECKOUT --source /tmp/publication-control-cost-fixture --output NEW_OUTPUT --source-manifest-sha256 b74045a6dbddaab6a3a53a75071d36c1098a1bacd3da26f3ea361709a89ba6d1 --request-latency-ms 1
```

The runner refuses source input beyond its explicit 1 MiB ceiling. This is a
fixture bound, not a production resource policy. It records 50 ms process-tree
RSS samples and scratch bytes at stage completion. Request counts/bytes describe
the in-memory adapter with 1 ms injected per modeled request; they exclude GitHub
artifact API, public HTTP, CI setup/downloads and hosted service latency. Artifact
custody and public probes use the retained test adapters. HEAD is counted without
the adapter's implementation-detail GET. Hash-helper bytes count Python
`hashlib.file_digest`; native library I/O and internal/incremental hashes are
explicitly excluded. Decoder counters count Parquet iterator/read entry points,
batches/rows and largest decoded batch, not native byte traffic or largest row.
SQLite SELECT counts include all observed selects; this fixture makes three
reference selects during preparation. These are cost observations, not permission
to omit complete integrity work. The measurement source digests allow comparison
with the exact instrumentation. State JSON serialization and fsync work are
counted separately for later journal comparisons.

The unchanged stage performs zero table downloads, decode passes and writes. The
explicit resume performs fresh full reconciliation before reusing writes. The
receipt does not qualify full-catalog performance, browser behavior or any release.

## Validated continuation and journal restoration

Continuation restoration accepts version 1 state with bounded phase, file and write
counts. Write transitions validate original condition, bytes and SHA256; success
requires a prior matching intent. Saved names must remain inside the attempt,
including after symlink resolution. Complete JSON state is limited to 32 MiB.
Remote journal restoration allows at most 16,384 events, 1 MiB per event and 64 MiB
in total. It checks listing names, exact length, version, nonce, chain, preparation
binding and legal transitions across the entire prefix before changing accepted
local state. Informational events remain valid. Event payloads remain local
evidence; derived write state is rebuilt in memory and checkpointed once.

`control-journal-after.json` repeats the same pinned fixture and 1 ms modeled request
latency after this change. Write-ahead per-event PUT/readback counts remain because
they protect crash boundaries and concurrent writers. Restore now serializes the
continuation once, rather than once for each write event. No publication proof is
reused across a restart; complete reconciliation reads remain required.

The SHA256 event chain detects changed/missing middle events. It has no independent
terminal anchor: deleting a suffix cannot be detected from the remaining prefix
alone. Conditional creation still fences the next sequence against another runner.
This change does not claim an additional terminal-anchor guarantee.

`Continuation.flush` fsyncs the file and parent directory around atomic replacement.
`save` fsyncs each artifact file before atomic replacement but does not fsync its
parent directory; abrupt machine/power loss can therefore lose that directory
entry. GitHub artifact acceptance and remote write-ahead events remain the durable
restart evidence. Required local dispatcher phase checkpoints remain unchanged.

## Writer coordination and freshness boundaries

| Maintained writer | Shared keys | Exclusion and final authority |
| --- | --- | --- |
| Capture/rebuild workflow and catalog library | `indexes/catalog.json`, derived immutable generations and history | Capture workflow concurrency; local recovery observes active capture runs. Final selector condition compares the exact prior version; immutable creates refuse replacement. |
| Viewer workflow/controller | `viewer-publications/manifest.json`, catalog locators, release files and attempt events | Workflow concurrency protects its jobs. Original pointer `IfMatch` or absence condition remains final authority; unique immutable releases and conditional event creation fence concurrent attempts. |
| Explicit local recovery dispatcher | raw catalog selector, accepted mappings, viewer selector and retained derived files | Held local `flock` inode/parent checks; active capture inventory observation; original protected versions and conditional writes. It does not share a workflow lock with cloud publication. |
| Explicit mapping publisher | accepted recovery mapping only; it does not advance the viewer pointer | Original accepted mapping condition; caller supplies lock, admission and cloud/input checks. It cannot rely on inventory as a lease. |

The capture inventory is an observation across five active statuses. It does not
inventory every writer and does not stop a job from starting after the scan.
Malformed, incomplete, slow or failed scans refuse writes. A stale successful scan
cannot survive a failed refresh. Shared commits always refresh inventory and
protected observations. Within one process, unchanged device/inode/size/mtime/ctime
custody reuses a verified local pin; changed custody rehashes it. A 1,000-immutable
write test plus another shared commit records 1 hash, 2 cloud checks and 2 protected
checks. The earlier implementation did 2 hashes for the same unchanged file.

Source, accepted mapping and viewer pointer checks are separate object reads.
Reading the pointer last cannot exclude a source or mapping change after its own
read. The original viewer compare-and-swap protects that pointer only. A dedicated
interleaving test records this cut point explicitly. The selected publication
retains exact source/mapping identities; a subsequent poll discovers later input
changes. No cross-object transaction or stronger lease is claimed or added.

## Inspect and explicitly resume an original attempt

Read-only discovery fetches bounded original-run artifact listings and emits one
validated descriptor with exact revision, run, artifact ID/digest/name and attempt.
Multiple matching artifacts require an explicit artifact ID; discovery never
downloads, reconciles or starts an attempt:

```sh
python apps/site/scripts/publish-viewer-r2.py describe-attempt --repository OWNER/REPO --run-id ORIGINAL_RUN --report resume.json
```

After checking out that exact original revision and restoring its accepted artifact,
an operator explicitly requests resume with the descriptor:

```sh
python apps/site/scripts/publish-viewer-r2.py publish --directory ORIGINAL_PREPARATION --resume --resume-descriptor resume.json --report outcome.json
```

Current GitHub environment defaults do not replace original descriptor fields;
explicit conflicting command options fail. Invalid combinations fail before SDK
client construction. Artifact custody failures name the exact ID, name, digest,
expiry or original-run mismatch. Every CLI exception replaces its report with a
failed command receipt and also writes `command-outcome.json` when the attempt
directory exists. Saving a diagnostic cannot replace the original exception.
Preparation receipts remain evidence of accepted preparation, not a final command
outcome. Journal restoration/reconciliation stays explicitly bounded by the
validated state/event limits; recorded verification is distinguished from current
full remote reconciliation and from public readback.

## One read-only verification command

`pipeline_status.py --verify-publication` records independent passed, pending and
failed checks in a durable local receipt. Supply the exact raw-selector SHA256
retained as output of the requested run; without that pin, attribution remains
pending. A saved selector also leaves live raw freshness pending. The original
run's metadata remains distinct from publication proof:

```sh
PUBLICATION_BROWSER_MODULES=EXISTING_PINNED_NODE_MODULES python scripts/pipeline_status.py --run ORIGINAL_RUN --verify-publication --raw-manifest CURRENT_RAW_SELECTOR_URL --expected-raw-manifest-sha256 ORIGINAL_OUTPUT_SHA256 --verification-receipt publication-verification.json --json
```

The command checks exact raw/viewer catalog and source identities, runs the
maintained review/recovery loaders against the selected public release, verifies
binding/review SHA256 pins and preserves withdrawn document IDs/reasons. It records
Pages module asset hashes. When the existing pinned Playwright runtime is
available, a fresh Chromium instance executes the deployed Pages bootstrap and
worker, calls its read-only information API and compares catalog/review/recovery
identities. Missing browser tools remain a specific pending check; reading asset
metadata alone never passes deployed runtime compatibility.

Category comparison fully reads/hashes a document table only when its declared
size is within 32 MiB. It verifies catalog metadata/count and decodes only stable
`document_id` plus the three classification columns in batches of 256 rows. Larger
tables remain pending before download. The receipt compares each reviewed or
withdrawn document's current catalog categories with retained review baseline and
selected categories. It never reinstates a withdrawn review or selects a new
publication. Bounded control reads, request counts and loader/runtime/asset pins
remain in the receipt. Public reads and browser startup have deadlines; no writes
or workflow dispatch/retry occur.

Status also exposes local recovery's exact next incomplete phase, uncertain write
keys and recorded verified-write count. These local observations explicitly have
not performed current remote reconciliation, and an unbound local recovery is not
attributed to an unrelated GitHub run. A later recorded journal failure supersedes
an earlier completion in status output.

Verification for this feature uses controlled HTTP/browser adapters and complete
small Parquet fixtures: 24 Python checks and 4 Node checks passed. No current
production completion or deployed compatibility claim is made by this local test.

## Supported publication routes before consolidation

The cloud operator uses `prepare`, `verify-prepared`, `describe-attempt` and explicit
`publish`/resume through `publication_cli.py`. GitHub artifact custody remains a
cloud-only acceptance boundary. The local recovery operator uses
`dispatch_corpus_recovery_publication.py` read-only admission, then explicit
`--execute`/`--resume` with its held local lock and accepted phase checkpoints.
Both routes build with `publish-filename-viewer.publish` and write viewer releases
through `publish-viewer-r2.upload`; both require original conditional versions.
Their different admission evidence remains necessary.

Caller inventory found no production caller for viewer `accept_recoveries`, the
Pages bootstrap migration, archive-only upload, or the no-prepared builder inside
`publisher.run`. Their callers were tests only. Mapping admission remains owned by
`publish_corpus_recovery_mappings.publish_mappings` under the local dispatcher;
accepted recovery publication goes through accepted preparation/controller output.
The compatibility routes can therefore be removed while retaining historical
immutable catalog locators and evidence. The dispatcher's `verify_coverage` was a
test-only wrapper around the maintained catalog validator; tests can call that
validator directly. The dispatcher's private rebuild wrapper exists only to get a
caller-owned durable workspace; a public workspace entry point will own that
normalization instead.

Consolidation retains one `ContinuedPublicationClient` for original-condition
replay in both cloud and local routes, one public caller-owned catalog workspace
entry point, and the shared viewer upload operation. The local dispatcher retains
its sealed-body admission, lock and durable phases; it now passes its original
protected source/viewer versions directly to the shared upload operation. The
remaining `check_selected_publication` is explicitly read-only: changed mappings
request accepted preparation and never build, download tables or mutate a pointer.

Removed product routes: direct viewer mapping acceptance, Pages migration,
archive-only writes, the no-prepared duplicate builder, test-only coverage wrapper
and both nested continuation client classes. Consumer support for historical
immutable snapshots remains; new accepted publication output requires current
manifest version 5. A named `ProtectedIdentity` keeps raw value/version/time/digest
fields together while retaining tuple unpacking at existing storage boundaries.

Client/guard capabilities fail before writes. SDK metadata must declare exactly
one mutation attempt. A callable full guard has one explicit named adapter; other
guards provide `check` and `shared_commit`. Plain SDK payloads now also use one
explicit `IfNoneMatch='*'` single PUT with independent complete readback, rather
than a managed multipart upload that could lose the original write condition.
Unsupported single-PUT files and oversized control output refuse before artifact
acceptance; resumed artifacts receive the same feasibility check before hashing.
The live verification Node suite is enrolled in the maintained `test:explorer`
script, which CI already runs.

The local dispatcher now persists the first viewer publication conditions apart
from versions advanced by its own writes. A restart therefore replays the original
selector condition even after that selector was successfully changed before runner
loss. Selected raw LastModified is checked and stored during accepted preparation,
preserving the displayed snapshot timestamp without changing an accepted manifest
later. Focused restart tests verify retained phase reuse and original conditions.

Measured code scope across publisher, dispatcher, guard client, attempt controller
and raw catalog entry point is 1,809→1,777 source lines (function count unchanged;
additional early validation replaces removed routes). The relevant improvement is
four unsupported publication routes removed and two replay implementations reduced
to one, with original-condition and feasibility checks shared. No speed percentage
is claimed for this structural consolidation. The expanded matrix passed 132 tests
plus 7 subtests; the final local original-condition/restart checks passed 36 tests
plus 5 subtests, and all 6 enrolled live-verifier Node tests passed.

## Early read-only check (ct-zb9y)

The scheduled publisher can now identify a no-op before full workspace setup,
PDF tool installation, historical input preparation and publication fixture tests.
A standard-library command reads only the selected raw manifest, viewer pointer,
accepted mapping, selected immutable viewer manifest and recovery status. It
compares complete release source/runtime identity and mapping presence/content,
verifies bounded recovery bytes and public readback, then separately rereads all
three protected controls. It never opens tables or constructs a mutation client.
Changed inputs or unsupported locked-runtime identity take full preparation.
Malformed, inaccessible or advancing controls fail closed. Code pushes still run
full fixture validation even when their preflight is unchanged. Every write still
uses accepted preparation, complete inventory verification, original conditions
and fresh protected-object checks; the preflight provides no write authority.

One shared identity helper hashes working-tree source bytes and fingerprints exact
locked/installed runtime versions, including `ijson`, Python version/implementation
and OS/architecture. Stat custody permits reuse within the same process only while
all source paths, sizes, inodes and modification/change timestamps remain unchanged.
The benchmark explicitly clears this source cache after collecting receipt pins,
before every timed command stage, so each starts cold while preserving reuse
within that command. Interpreter/import startup and actual GitHub Actions setup
are excluded from these fixture stage measurements. Unrelated documentation remains
outside release identity. The helper removes the duplicated early/full identity implementation.

The fixed signer is a deliberate narrow exception to preferring maintained SDKs.
The maintained alternative is locked botocore plus jmespath, python-dateutil, six
and urllib3: their five current wheel payloads total 16,358,049 bytes, before an
installer/runtime setup and unpacked files. Installing those only for ten fixed
control GETs would add a second dependency installation path to the no-op job.
The adapter instead supports only AWS Signature Version 4 GET, region `auto`,
service `s3`, fixed HTTPS R2 account host/bucket and five exact control-key forms.
It accepts no query, caller headers, body, session token or write method. It
normalizes aware times to UTC, refuses naive times and unsafe access-key headers,
disables redirects before credentials can be forwarded, closes rejected/error
responses and performs no automatic retry. Tests compare every allowed key form,
UTC date transition and signed headers against maintained botocore. The cost is
ownership of these fixed authentication rules; any expanded auth/request surface
should use botocore rather than extend this signer. No new external package is
needed on the early path.

Local evidence in `evidence/control-preflight.json` retains both absent and empty
mapping cases: 8 private control GETs, 2 public GETs, zero table reads and zero
publication writes. Input/source/runtime/review/mapping changes, concurrent input
advance, malformed/oversized/incomplete bodies, HTTP errors, exact key/endpoint
allowlists, redirect refusal and retained fresh write gates have focused tests.
These are local fixture observations, not hosted-job performance qualification.
The workflow records elapsed time from its first step and observed host receive
bytes, with exclusions for runner allocation, artifact upload and post-job cleanup
and a warning that host counters include background traffic. **Complete real
unchanged-job duration and downloads remain pending a future deployed unchanged
run.** No workflow was dispatched, retried or deployed for this work.

Local verification passed 147 tests across preflight, protected reads, state bounds,
accepted attempts, CLI outcomes and R2 publication; the final preflight-only run
passed 44 tests including the added exact `ijson` version check. Pending hosted
qualification is tracked separately by `ct-x7vx`, which depends on this change.
