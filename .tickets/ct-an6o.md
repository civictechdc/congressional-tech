---
id: ct-an6o
status: open
deps: []
links: [ct-680z]
created: 2026-11-08T17:42:58Z
type: feature
priority: 2
assignee: mikewolfd
tags: [identity, dependencies]
---
# Hash only the packages each parser imports into its producer identity

Every root uv.lock change moves all eight producer parser identities, because the whole lock is hashed into them, so patch-only security bumps (aiohttp, pyasn1, lxml) each need a reviewed identity mapping. reading_version_diagnostics.py already walks each parser's imports; hash only the locked versions of those packages so unrelated security patches stop changing data identities. Surfaced by the ct-680z sweep (2026-11-08).


## Notes

**2026-11-08T20:01:33Z**

2026-11-08 implementation on branch claude/ct-an6o-import-hashing (432e1ca4, 21e67906; not pushed or merged). The eight record/filename producer identities now hash declared sources, schemas and values plus the locked name/version/source of packages their parser code imports (versions.producer_version; walk stops at digest-verified body custody, table I/O, worker transport; no installed metadata; an unattributable import refuses). Closures: appearance x4 = lxml, pyarrow, pydantic (+deps); meeting x2 = jsonschema, pyarrow, pydantic; committee = pyarrow, pydantic; filenames = jsonschema, pyarrow, pydantic (via house_naming.filenames). Migration: the old rule computes exactly the eight pinned IDs on this tree; the reviewed map translates the eight new fingerprints to those same IDs, so no pin, selector or row moves. Focused checks: 128 passed (filename readings, producer identities, model job, producer proof; partial); earlier 761 passed in a 14-file run, whose failures were the old whole-lock test expectation and dirty-tree refusals, both resolved. Planted wrong mapping refused by the model spec. aiohttp, pyasn1, urllib3, certifi, pillow, pypdf, boto3 bumps leave all eight identities unchanged; lxml moves only appearance; jsonschema meeting+filenames; pydantic-core and pyarrow all eight.
