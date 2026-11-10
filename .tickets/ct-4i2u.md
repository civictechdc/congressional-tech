---
id: ct-4i2u
status: open
deps: []
links: []
created: 2026-11-10T15:41:12Z
type: bug
priority: 1
assignee: mikewolfd
tags: [readings, versions, ci]
---
# Reading-version evidence may hash differently on Linux: the closure lists house_naming/Engine.py through a case-insensitive disk

Found 2026-11-10 while recording the MODS branch's reading-version equivalence (.cache/archive-release/investigations/mods-rebase-20261110/equivalence/). The file closure that feeds the text readers' workspace_sha256 evidence lists house_naming/Engine.py, which is engine.py resolved on this Mac's case-insensitive file system. A Linux runner (case-sensitive) may resolve the import differently and compute a different digest, so doctor and CI could disagree with the Mac about whether reading evidence changed. Not checked on Linux.

## Acceptance Criteria

The closure is computed from module names resolved case-exactly; the same digest is shown to come out on the Mac and on the hosted Linux runner for the current tree, or the difference is explained and fixed; a test fails on a path whose case differs from the file on disk.

