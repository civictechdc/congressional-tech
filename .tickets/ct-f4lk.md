---
id: ct-f4lk
status: open
deps: []
links: []
created: 2026-11-17T18:51:21Z
type: task
priority: 3
assignee: mikewolfd
tags: [ci, dependencies]
---
# filelock 4.2.0 to 4.2.1 clears 17 more Dependabot alerts

Found while doing ct-na9t (2026-11-17): after the aiohttp bump, 17 open alerts remain on filelock 4.2.0 in `uv.lock`; the patched version is 4.2.1.

## Acceptance Criteria

One pull request moves only filelock in `uv.lock` (with `/opt/homebrew/bin/uv`), `definition-change.py` reports the model definition unchanged, and the alerts close.
