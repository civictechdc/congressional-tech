# Viewer publication commands

These commands publish and inspect the **filename viewer**: the public site that looks up congressional documents by filename. The built files live in Cloudflare R2 under `viewer-publications/`. They are derived from the raw archive. These commands do not capture new documents and do not rewrite archive bodies or `indexes/`.

The day-to-day publisher is `apps/site/scripts/publish-viewer-r2.py`. It imports `publication_cli.py` from this folder. Run it from the repository root after `uv sync --locked`.

## `publication_cli.py`

One interface for a viewer publish attempt. Run these commands through `apps/site/scripts/publish-viewer-r2.py`.

| Command | What it does |
| --- | --- |
| `prepare` | Builds a local attempt directory and writes a report. It does not upload. |
| `verify-prepared` | Checks that a prepared directory still matches the attempt you intend to publish. |
| `publish` | Uploads that prepared attempt. Resume requires the original attempt identity, so a second process cannot publish a different attempt under the same name. |
| `describe-attempt` | Reads an existing attempt and prints what it was. It does not change remote objects. |

A failed command replaces a stale success report before it opens a client that could write.

## `pipeline_status.py`

Reads the status of a capture or publish **without changing it**. Give it a GitHub Actions run ID. It asks GitHub for that run and reads the public heartbeat object (`status/raw-source-sync.json`). It attributes heartbeat numbers to the run only when the run, attempt, and git revision match. It does not resume work, write status, or estimate a finish time.

```bash
.venv/bin/python scripts/publication/pipeline_status.py --run RUN_ID
.venv/bin/python scripts/publication/pipeline_status.py --run RUN_ID --json
```

Offline, pass saved GitHub and heartbeat JSON with `--github-json` and `--progress`. Details and the extra flags are in [`docs/pipeline-status.md`](../../docs/pipeline-status.md).

## What this folder does not contain

The guarded upload, the resume journal, and the read-back checks live in [`packages/viewer_publication`](../../packages/viewer_publication/README.md). The cheap "already published?" check that runs before dependencies are installed is `scripts/publication_preflight.py`.
