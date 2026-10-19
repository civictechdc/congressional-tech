# One accepted viewer plan (ct-bpyj)

Local recovery and cloud publication now consume `AcceptedViewerPlan`: protected
source/mapping/viewer records, source/code pins, accepted recovery status, exact
file inventory, and the original release/selector conditions. The plan wraps the
maintained issued inventory; it introduces no persistence format, verifier
registry, artifact service or resume authority. Mutating its nested facts or file
custody invalidates that inventory context. Recovery-only plans refuse full upload
before any PUT.

Cloud `verify_prepared` keeps its receipt/result/runtime/phase checks and required
GitHub artifact acceptance. Common acceptance owns the prepared-file checks once;
the uploader consumes the accepted file list and recovery result. Output capacity
admission remains before fresh file hashing. Local preparation passes its existing
sealed-body catalog-pair proof to the real builder, retains returned file proofs,
and saves the same `recovery-prepared.json` format already used by cloud attempts.
Original protected inputs and release/conditions live in the existing local
continuation state before upload. Existing phase files and original-condition
replay remain; a fresh process independently hashes every restored file once.

`corpus_recovery.publication.publish_imported` now owns the Store adapter and domain
phases. The dispatcher keeps runtime admission, eager pre-lock source checks,
source pins, lock, SDK configuration, guard and diagnostic failure handling. The
source-versus-proposed catalog retention and sealed body coverage are unchanged.
`corpus-recovery` explicitly declares its one-way `viewer-publication` dependency;
no third-party version changed. Cloud release identity includes both the new plan
and merged reconciliation helper; local runtime pins cover the source subtree.

## Bounded comparison

The baseline is exact `dfeed08aa87afb1e481a5ee52de7409e4470745c`. The candidate
includes the reviewed main refresh `014303ed0a292bc418e38070776734ce0feaae07`.
The intervening reconciliation observer does not run on this measured success
path. Each arm runs the real builder, real pair validation, local prepared phase
and guarded uploader over the same seven-source/six-group fixture. External
storage/public transport is in memory. The declaration capped each arm at two
minutes, 2 GiB sampled process RSS and 1 GiB scratch; no real upload occurred.

| Complete preparation + upload | Before | After |
| --- | ---: | ---: |
| Output `file_digest` passes / bytes | 554 / 229,623 | 0 / 0 |
| Output `file_identity` passes / bytes | 269 / 49,506 | 270 / 50,688 |
| Combined observed helper passes / bytes | 823 / 279,129 | 270 / 50,688 |
| Recovery scans | 1 during upload | 1 during preparation |
| Full GET / HEAD / PUT | 278 / 270 / 273 | 281 / 270 / 273 |
| fsync calls | 554 | 557 |
| JSON serialized characters | 825,186 | 927,970 |

These helpers perform **553 fewer complete output hash passes and hash 228,441
fewer output bytes (81.8%)**. The candidate adds one accepted-status file hash;
the original one recovery scan moves earlier rather than disappearing. Three
GETs and three fsyncs retain protected input/plan facts. Counts distinguish actual
GET calls from the mock HEAD implementation's internal method delegation. They
exclude incremental digest updates in transfer/decoder/native code, and therefore
do not claim to count all hashing or physical disk reads.

All 269 payload hashes match. Every normalized prepared-manifest value, complete
published manifest, recovery status, publication result, original condition and
mutation key/condition count matches. Only prepared issuance `published_at` is
normalized; both uploads use the same fixed release/time. Changed source-code
fingerprints in pointer `full_release_inputs` and nested recovery inputs are
retained separately as expected provenance changes; every other pointer value
matches. Candidate restoration issues exactly 271 fresh file hashes / 76,027 bytes,
then reuses custody proof without another recovery scan or builder invocation.

The tiny arm does **not** establish a speed or memory gain. Recorded total times
are 0.4955 seconds before and 1.0469 after; one arm each, and the baseline arm
shared the machine with focused tests. These are diagnostic values, not a latency
qualification. Inventory path/custody checks, context serialization and retaining
original plan facts add work; hundreds of empty ID shards make the removed byte
hashing cheap in this fixture. JSON/checkpoint counters expose that tradeoff.
A representative larger-payload comparison would be needed to establish a
break-even point; no full-catalog run is authorized or claimed. Sampled RSS is
128.8 versus 130.0 MB, not a hard/native allocation bound or an improvement.

## Verification and evidence

Seven new local tests exercise real preparation/upload, the moved domain entry
point with actual source pair/coverage checks, original-condition failure/resume,
plan mutation, legitimate recovery-plan/full-upload refusal, and same-size
corruption. A separate Python subprocess restores all files once and independently
refuses corruption; it cannot call a builder, source revalidator or external client.
Existing cloud tests preserve full/recovery/no-op/superseded/failed outcomes,
artifact refusal, runtime changes, original release replay and lost-ack behavior.
Existing dispatcher tests still test phase/guard/refusal behavior with explicit
stubs; they do not supply the real-integration proof. Dirty-source tests verify
both new release-identity paths.

The focused run passed 221 checks and seven subtests, with one environment failure:
my isolated environment omitted the existing development dependency PyYAML. A
locked offline sync of only this worktree added it; that exact failed test then
passed. Thus 222 distinct focused checks and seven subtests passed across those
retained logs. No full suite, hosted, acquisition or held-out run occurred.

Primary evidence: `output/efficiency-debt-20261019/accepted-plan/` contains the
predeclared plan, exact baseline source snapshot, immutable fixture, `measure.py`,
`comparison.json`, both accepted receipts/payloads, source/import hashes, test logs
and final receipt. Initial failed tests, pre-cleanup draft arms and telemetry
corrections remain separately retained; they are excluded from the accepted
comparison. The initial counter missed explicit-file builder modules outside
`sys.modules`; the accepted shared counter covers those aliases in both arms.
The compact committed evidence pins the accepted receipts and runtime sources.
