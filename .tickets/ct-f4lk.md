---
id: ct-f4lk
status: closed
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

## Notes

**2026-11-17: closed**

Merged as pull request 194 (e7ac121a): filelock 4.2.1, pyasn1 0.6.5, protobuf 6.33.5 and setuptools 84.1.0, each with a constraint floor; nothing else moved in the lock and the model definition is unchanged. Clears 23 alerts (filelock 17, pyasn1 4, protobuf 1, setuptools 1).

Still open after it, on ct-hs34 item 3: lxml and soupsieve (they move byte-hashed parser versions), idna and requests (on the fetch and address path), and eight alerts in other lock files (rustls in `packages/source-fetch/Cargo.lock`, astro and picomatch in `apps/site/package-lock.json`, dnspython in `apps/explorer_mcp/uv.lock`). Left until one scheduled night has passed on today's changes.
