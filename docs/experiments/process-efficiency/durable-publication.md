# Accepted preparation and explicit publication restart

The command line now separates `prepare`, `verify-prepared` and `publish`.
Preparation makes no remote writes. It records complete output size/hash inventory
(including every ID shard), source/viewer/accepted versions, source selection,
compression policy, code revision and source hashes, installed dependency fingerprint,
review identities, and the original immutable release plan. A current recovery-only
refresh prepares its two required inputs. An exact no-op needs no preparation.

The workflow accepts the preparation as a GitHub artifact before publication,
using compression level zero. Publication reads GitHub artifact metadata and requires
its original run, exact digest, name and unexpired state. A restored artifact is
independently checked against every local inventory entry; a warning from the
artifact downloader cannot substitute for these checks.

Every publication mutation uses GuardedPublicationClient and its original explicit
condition. A dedicated `viewer-publications/attempts/<attempt>/` journal conditionally
creates an immutable event before the mutation and a verified outcome afterward.
Events form a SHA256 chain, retain a local copy, and bind accepted preparation and
artifact custody. A competing writer cannot claim the same sequence. Journal writes
also use the guarded conditional/full-readback boundary, without recursive logging.

Resume is manual and requires the original artifact run, revision, ID, digest and
attempt. The workflow checks out that exact revision, restores accepted files, reads
the remote journal, reconciles uncertain writes against current remote bytes, and
reuses the original release and conditions. No scheduled job selects or retries a
failed attempt. A superseded source/viewer/mapping prevents stale selection. Failures
to save diagnostics are attached to the original error instead of replacing it.

Local verification covers forced probe failure, lost acknowledgment, abrupt runner
loss after commit, recovery pointer loss, full shard corruption, artifact refusal,
missing journal events, concurrent journal append, stale mutable inputs and changed
runtime/review bindings. Mock-store evidence verifies state transitions, not hosted
GitHub/R2 service behavior or production retry duration. The local fixture receipt
records artifact copy/restore plus journal work as separate elapsed costs.

CLI example (readable placeholders):
```
python apps/site/scripts/publish-viewer-r2.py prepare --directory viewer-preparation --run-id RUN --run-attempt 1
python apps/site/scripts/publish-viewer-r2.py verify-prepared --directory viewer-preparation
python apps/site/scripts/publish-viewer-r2.py publish --directory viewer-preparation --artifact-id ID --artifact-digest SHA256 --run-id RUN --repository OWNER/REPO
```
An explicit later invocation adds `--resume --attempt ORIGINAL_ATTEMPT` and uses the
same restored preparation and original artifact metadata.

No workflow was dispatched and no public objects were changed during implementation.

Independent review added per-event unpredictable nonces, persisted locally before
PUT, so an ambiguous response cannot accept another runner's identical event.
A restored artifact reconstructs the complete local journal. An explicit resume
can also start the original attempt after an initial journal outage: read-only
absence and fresh protected-input checks precede its conditional first event.

Verification: 72 tests plus two subtests passed before these review corrections;
the corrected attempt/continuation matrix then passed 29 tests. The publisher and
compression fixture matrix passed 41 tests. Further integration results are recorded
in the implementation receipt. The local retry fixture performed zero builder calls
and zero repeated release-payload writes on resume; local artifact copy/restore and
journal costs are retained in output/process-efficiency/retry-fixture.json.

The aggregate review removed repeated mutable-input polling for immutable,
conditionally created release files. Fresh protected-input checks still precede
shared selection. A resumed process can reuse its own full reconciliation readback
only for the identical client, bucket, key, hash, size and current HEAD version.
The proof stays in memory; restored JSON cannot grant it. Different clients and
uncertain objects still require complete readback.

The final focused matrix passed 40 tests and two subtests in 22.90 seconds. Its
successful 273-write fixture required 548 journal PUTs, 548 complete journal
readbacks plus one initial absence check, 269 payload-version HEADs, and 12 mutable
identity GETs. Journal content totaled 236,828 bytes. These are explicit normal-run
costs of durable per-write recovery; the implementation does not claim that retries
are free or that the journal minimizes remote request count. Counts exclude public
HTTP probes and GitHub artifact metadata requests.
The hash chain serializes each event and its readback even when payload transfers
use multiple threads. Hosted event latency may therefore add normal success
critical-path time. The next delivery measurement should separate artifact upload,
payload transfer, journal waits and public probes on one accepted preparation.

The same mock-store retry fixture performed no rebuild and no repeated release
payload writes. Local artifact copy took 0.050 seconds, restore took 0.109 seconds,
and retry including journal work took 1.063 seconds (1.172 seconds including
restore). This measures local transition overhead, not network delivery latency.
The exact receipts are retained in `evidence/success-request-counts.json` and
`evidence/retry-fixture.json` alongside this report.


Release selection now persists `full_release_inputs` on the viewer pointer. It
hashes the working-tree bytes of the builder's dynamic helper set, congress_api
Python source closure, review identities and dependency lock files, plus Python
and the relevant installed publication libraries. This intentionally conservatively
rebuilds after congress_api source edits. Dirty transitive edits count; Git commit
identity and unrelated documentation do not. Old pointers lacking this identity
require one complete preparation. Mapping-only changes retain recovery preparation;
absent and empty accepted mappings stay distinct. An artifact retains its original
identity and refuses resume if any of those inputs change.

Complete control reads now enforce per-kind ceilings before accumulating bytes:
4 MiB for manifests/selectors, 16 MiB for accepted mappings, and 32 MiB for
recovery status. Both declared and actual streamed lengths are checked, including
exact descriptor length where available. Complete SHA256 and browser CORS checks
remain. Bodies close on success and errors. `open_public` retries only connection
opening; body-read errors propagate without a hidden retry. These limits do not
apply to streamed catalog payloads and do not permit partial verification.

Guarded transfer receipts now have weak issuance ownership: discarded JSON/journal
results retain no registry entries. Active results still own their proof until
consumption. Reference-counted key locks include waiting writers and are removed
only after the last holder/waiter exits. A recovery JSON write consumes its exact
current-version proof instead of repeating full readback; plain clients retain
complete independent readback. Restart reconciliation still performs complete
remote reads and checks current versions before replay.
