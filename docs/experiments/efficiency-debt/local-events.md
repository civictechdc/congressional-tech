# Local events own recovery (ct-2ut4)

Local recovery now syncs one event authority instead of replacing the entire
continuation file for every write and then separately appending the same event.
`LocalContinuation` appends write intents before requests and verified results
after complete readback. Phase and control boundaries append full state before
replacing the derived `continuation.json`. The cloud journal does not change.

The dispatcher no longer separately advances protected versions: the verified
event advances both the write receipt and the existing versions map. Guards keep
that map's object identity. Every explicit resume creates fresh readback proofs,
checks accepted phase files, and reconciles current remote bytes before reuse.
The local route requires no remote journal or artifact service.

`read_local_journal()` serves both recovery and read-only status. It validates
sequence, preceding-record digest, binding, state shape, transitions, and limits
before returning observations. Status sees a durable intent even when the derived
checkpoint predates it or is missing. Legacy checkpoint-only status explicitly
labels the latest event state unknown and its counts potentially stale. Neither
status nor recorded verification grants current readback proof.

## Same-input comparison

Baseline: `75820f3f6dcb5ea52fece46c77af27ffd1a5759a`. Candidate:
`0c2b782d15a1277d78ba0d7867f6b612d19e2e96`, clean tracked files. The maintained
measurement loads the exact baseline continuation source from Git and repeats the
baseline dispatcher's journal and protected-version callbacks. The candidate
uses the committed local helper. Both use the same instrumentation, interpreter,
mock store, and generated inputs. Source hashes are retained in
[the receipt](local-events-evidence.json).

The declared ceiling was 128 writes, four accepted phases, three paired repeats,
120 seconds per arm, 64 MiB scratch, and 512 MiB sampled process-tree resident
memory. Actual generated request bodies total 9,874 bytes. There is no network,
acquisition, catalog build, cloud attempt, or current-catalog qualification.

| Measured local work | Baseline | Candidate |
| --- | ---: | ---: |
| All serialized JSON characters | 5,493,025 | 511,187 |
| Full state serializations | 263 | 12 |
| `fsync` calls | 783 | 276 |
| Median elapsed seconds | 0.153948 | 0.079474 |
| Final retained scratch bytes | 117,247 | 245,262 |
| Final event history bytes | 75,973 | 203,988 |

Work counts match in every repeat. All six runs produce the same complete state,
257 ordinary event facts after excluding timestamps, all 128 body hashes, 128
PUT requests, and 128 complete readbacks. Each resulting local authority restores
the exact final state with no inherited ephemeral proof. Maximum sampled resident
memory was 53,149,696 bytes; this small fixture supports no memory improvement
claim. Wall time ranges were 0.151776–0.170243 seconds before and
0.079252–0.081343 seconds after. These short local runs measure this fixture only;
the stronger result is removing 507 syncs and about 91% of serialized characters.

The tradeoff is larger retained local history: full phase/control records make
that history authoritative, adding 128,015 retained bytes here. The state remains
limited to 32 MiB; ordinary events permit 1 MiB, full state records permit the
state limit plus 1 KiB metadata, and the entire history permits 65,536 records and
256 MiB. These are admission limits, not a complete native-memory budget. Larger
inventories can reach the history limit. Partial, broken, excessive, and failed
histories are preserved and refused, never silently truncated or restarted.
Runtime pins prevent silent migration of older attempts.

## Verification and retained evidence

At the candidate revision, the complete publication package tests plus affected
dispatcher and status tests passed: **165 passed, 7 subtests passed in 33.20s**.
New focused cases cover every accepted local phase; missing and stale derived
checkpoints; uncommitted, committed-but-unrecorded, and verified requests; current
body conflicts; exact incremental state-byte accounting; retained failure facts;
illegal transitions; partial/removed/oversized events; sync failure before a PUT;
checkpoint failure after phase acceptance; guard map identity; and read-only
status without constructing a mutable continuation.

Raw evidence remains under
`output/efficiency-debt-20261019/local-events/run-final/` with the focused test log
in its parent. The compact tracked receipt pins their hashes and exact sources.
The earlier `run-75820f3` is retained as preliminary evidence from before the
shared status parser was extracted; the final comparison supersedes it.
The ticket remains in progress pending independent review and merge.
