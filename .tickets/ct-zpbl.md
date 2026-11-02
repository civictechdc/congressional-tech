---
id: ct-zpbl
status: open
deps: []
links: [ct-deh9]
created: 2026-11-02T17:45:21Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [versions, phase2, post-release]
---
# Parser versions: a declared version is the identity; the code hash only warns

Owner direction 2026-11-02: simplify parser versioning so nothing is recomputed unless absolutely necessary; the minimal code hash should just warn, with a manual check. Today parser_version is a byte hash of hand-listed files plus the whole uv.lock (AGENTS.md 'Byte-hashed parser pins'). That is too broad: any lock change moves every version and forces proofs or recomputes; the compatible-version registry, with its lock_only/whole/predicate entries and proofs, exists to undo that. It is also too narrow: parsers import unhashed workspace modules (sniff 17, html/xml/json models/xml.py and base.py), so a real change can move no version (RCA items 1-2, .cache/archive-release/investigations/rca/RCA.md). Lead check 2026-11-02: this release is not affected; sniff's semantic imports are unchanged since 2026-10-20, and the html proof found 0 differences on 124,651 rows. Direction: each parser declares a version, and readings are keyed by it. Recompute happens only when someone deliberately bumps it because outputs change. The minimal code hash (the parser's import closure: its own modules plus the locked packages it imports; r4-rca 1f6effdf already computes the package part) is recorded as provenance. When it drifts without a bump, CI and doctor warn and attach a cheap sample proof; a person either bumps the version or acknowledges the warning. It never blocks and never forces a recompute.

## Acceptance Criteria

Plan with /evolutionary-refactoring first: (1) a declared version per parser, carrying the current pins over unchanged so no data is redone at the switch; (2) the import-closure hash recorded and compared in CI and doctor as a warning with a sample proof; (3) delete what becomes dead (whole-lock hashing, lock_only and whole registry machinery, pinned test hashes) rather than keeping it beside the new rule; (4) update AGENTS.md's byte-hashed pins section and publish-model.json flow; (5) a test proving a dependency bump moves no version and forces no recompute, and that a semantic edit without a bump warns.

