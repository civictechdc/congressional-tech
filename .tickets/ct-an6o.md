---
id: ct-an6o
status: closed
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

**2026-11-09T16:22:11Z**

2026-11-09 rebased onto main e55e9c76 (worktree .claude/worktrees/ct-an6o-rebase; not pushed or merged). One map: 973298d7's body_text-lock entries were old-rule (whole-lock) fingerprints that producer_version cannot compute, so they are deleted; the body_text lock added nothing to any producer's import closure, so the seven non-MODS new-rule fingerprints are unchanged and their entries stand. MODS (ct-79j1/ct-rg34) new-rule fingerprint 8a34087e maps to the published 8a0023a9. Main's old rule and this branch both compute exactly publish-model.json's pins (all eight; catalog_version included); publish.json model_spec sha256/size match. CI 42518011172 failure (test_model_single_value_groups patched filenames.version_digest) fixed; the rebase also needed body_text_evidence to call _fingerprints (main's 61f51a92 used ImportClosure.fingerprints). Targeted files pass one at a time. reading-version diagnostics drift on readings + 4 body-text parsers (workspace_sha256) exists on main too; on the branch only the hashes differ because versions.py changed.

**2026-11-09T16:25:33Z**

Owner signed off the map equivalence 2026-11-09 (questions tool: 'Sign off (Recommended)'): 7 unchanged producers' import-closure fingerprints reproduce the ct-680z-reviewed entries byte-for-byte; MODS maps 8a34087e -> 8a0023a9 (activated today). Full lane queued after the ct-8cno roster lane; merge after it passes.

**2026-11-09T20:18:11Z**

2026-11-09 merged to main as 16084de5, a fast-forward from 7dd01f79. Full lanes passed on the pre-rebase tip 77328aaf: production-offline 12,327 passed, storage-loopback 34 passed. After the rebase, the 8 overlap files passed (producer identities, single-value groups, filename readings, daily producer records, daily producers, readings budget backfill, spicy-regs inputs, body-text derivation), and doctor shows the same 5 reading-version warnings as before. filenames.current_version() is still c65e505e, equal to the catalog_version pin. Validate Committee Explorer dispatched on 16084de5 (run 42691558640).
