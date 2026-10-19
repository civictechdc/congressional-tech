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
| `attempt` | Identifies one publish attempt (run, revision, artifact digest) so a later publish cannot claim a different attempt. |
| `verify` | Read-only checks that a published viewer object matches the attempt that was prepared. |

## What has to stay outside this package

`scripts/publication_preflight.py` decides whether CI can skip a rebuild. It runs before `uv sync`, so it cannot import this package. It uses `scripts/viewer_release_identity.py`, which stays a standard-library module for the same reason. Both are part of the release fingerprint: a publish records the source files and locked dependency versions it ran.

Recovered documents enter the archive through [`corpus_recovery`](../corpus_recovery/README.md) before this package ever publishes a viewer built from them.
