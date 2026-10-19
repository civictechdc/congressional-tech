# Viewer publication

Python library for publishing the **filename viewer** without rewriting the raw archive.

The filename viewer is the public lookup of congressional documents by filename. Its files live in Cloudflare R2 under `viewer-publications/`. They are built from the archive. This package is the write boundary for those derived files: one conditional upload, a full read-back, and a local journal so a crashed attempt can resume from what already landed.

People publish with `apps/site/scripts/publish-viewer-r2.py`. That script calls [`scripts/publication/publication_cli.py`](../../scripts/publication/README.md) for `prepare`, `verify-prepared`, `publish`, and `describe-attempt`. Import this package when code needs the guarded client or the journal directly.

```python
import viewer_publication
```

Install it with the workspace (`uv sync --locked`).

## What you can ask it to do

| Module | Role |
| --- | --- |
| `client` | `GuardedPublicationClient` accepts only derived catalog and viewer keys, requires a condition on every write, and disables SDK retries. After a put, it reads the object back and returns a `VerifiedTransfer` (bucket, key, size, SHA-256, and ETag). `require_publication_client` rejects a client that could retry a write on its own. |
| `continuation` | `Continuation` and `DurableJournal` record each accepted phase. Resume returns the recorded result when the artifacts still match. A changed file is a refusal, not a silent rerun. |
| `local` | `LocalContinuation` owns deliberately local recovery through synced `events.jsonl` records. `read_local_journal` inspects the same bounded history without changing files or granting current readback proof. |
| `reconciliation` | Records the latest bounded per-object read observation, outcome, and next check during explicit reconciliation. Its file never supplies readback proof or write authority. |
| `plan` | `AcceptedViewerPlan` binds protected source/mapping/viewer identities, code pins, accepted recovery status, exact file inventory and original release/selector conditions using the existing issued inventory proof. Both local and cloud routes consume it; cloud artifact custody remains separately required. |
| `attempt` | Identifies one publish attempt (run, revision, artifact digest) so a later publish cannot claim a different attempt. |
| `verify` | Read-only checks that a published viewer object matches the attempt that was prepared. |

## What has to stay outside this package

`scripts/publication_preflight.py` decides whether CI can skip a rebuild. It runs before `uv sync`, so it cannot import this package. It uses `scripts/viewer_release_identity.py`, which stays a standard-library module for the same reason. Both are part of the release fingerprint: a publish records the source files and locked dependency versions it ran.

Recovered documents enter the archive through [`corpus_recovery`](../corpus_recovery/README.md) before this package ever publishes a viewer built from them.

The local recovery dispatcher uses `events.jsonl` as its recovery authority. It
syncs each write intent before the request and each verified result after complete
readback. Phase and control boundaries append a full state record before replacing
the derived `continuation.json` checkpoint. Losing that checkpoint does not lose
accepted events. Status reads validated events, and labels older checkpoint-only
observations as potentially stale. An explicit resume still checks phase files
and current remote bytes; recorded verification alone grants no reuse.

Local histories permit at most 65,536 records and 256 MiB total. Ordinary records
permit 1 MiB; a full state record permits the existing 32 MiB state limit plus
1 KiB metadata. Partial, broken, or excessive histories are retained and refused,
never truncated or retried automatically. These are local admission limits, not
a complete process memory budget. The cloud journal and its remote custody rules
do not change. Runtime source pins distinguish older attempts; this change does
not migrate their local histories automatically.

Explicit reconciliation replaces `reconciliation-progress.json` as it reads each
object. The observation names the key, bytes read, declared body length, object
count, outcome, and exact next check. It binds the input identity and carries a
scan ID and timestamp. Status shows it as the last recorded observation, which
may be stale if the producer stops. It never claims public verification or
permission to resume. Read success requires the complete body and existing
size/digest/version checks; scan completion follows the state checkpoint.

Each object produces at most 36 observations, plus scan start and completion.
Only the latest file is retained, capped at 16 KiB. These observations add no
`fsync` calls, durable journal events, remote requests, or retries. Observation
write failures cannot replace the original reconciliation outcome. Diagnostics
use fixed messages and do not copy transport exception text or credentials.

The plan adds no file format or resume authority. Cloud preparation keeps its
existing receipts and required GitHub artifact acceptance. Local preparation
keeps its existing prepared phase and files, adding the accepted recovery status
file and retaining original input/release facts in the same continuation state.
A same-process transfer reuses file proofs only under unchanged custody; a fresh
process independently hashes every restored file once. Recovery-only plans cannot
enter full upload. Capacity admission precedes fresh hashing, and changed pins,
conditions or file custody remain refusals.
