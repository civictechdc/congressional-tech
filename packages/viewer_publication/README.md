# viewer-publication

Import name: `viewer_publication`.

This package holds the viewer publication code that runs after the workspace
is installed: the guarded object client, publication continuation, attempt
runner, and read-only verification. `scripts/viewer_release_identity.py` stays
a standard-library module so publication preflight can run before `uv sync`.

The modules under `scripts/` with the same names re-export this package so
existing `sys.path` imports keep working.
