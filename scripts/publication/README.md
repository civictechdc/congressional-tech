# Archive publication commands

The maintained publisher is `viewer_publication.archive_publish_job`. It builds
and admits an engine release before the shared release gate selects it. Inspect
an owner-prepared job specification locally with:

```sh
.venv/bin/python -I -m viewer_publication.archive_publish_job --spec path/to/publish.json --plan
```

The archive contract and canary must pass before the release pointer changes.
Publish, backfill and maintenance share the workflow concurrency group in
`.github/workflows/archive-jobs.yml`. The capture workflow uses the same group.

The guarded client and raw journal helpers remain in
[`packages/viewer_publication`](../../packages/viewer_publication/README.md).
The old v6 publisher, renderer-upgrade continuation, preflight and status CLIs
are retired. Rollback uses the previous application revision from git history.

Runtime distribution still uses `.github/actions/setup-local-job-runtime` and
its pinned runtime descriptor. `publish-docspec-runtime.py`, the PDF backfill
wrapper and the origin-rule wrapper remain available for their retained owner gates.
