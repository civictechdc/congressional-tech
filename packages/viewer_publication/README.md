# viewer-publication

Import name: `viewer_publication`.

Upload a prepared filename viewer and resume a stopped upload from its saved record.

Use this after the workspace is installed and a filename viewer is ready to publish. The library sends each write once, reads the uploaded bytes back, and keeps a record of each write. It checks the published viewer against the raw catalog.

Run `python apps/site/scripts/publish-viewer-r2.py`. It calls `scripts/publication_cli.py` for `prepare`, `verify-prepared`, `publish`, and `describe-attempt`.

`scripts/publication_cli.py` and `scripts/viewer_release_identity.py` live in `scripts/`. `scripts/publication_preflight.py` imports `scripts/viewer_release_identity.py` before the workspace is installed.
