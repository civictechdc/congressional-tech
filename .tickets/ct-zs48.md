---
id: ct-zs48
status: open
deps: []
links: [ct-79j1]
created: 2026-11-08T20:05:51Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [congress_api, mods, witnesses]
---
# Split Norton and Lipinski's combined MODS witness line in CHRG-114hhrg93258

Found by the ct-79j1 survey (2026-11-08): witness 10 of CHRG-114hhrg93258 joins 'Hon. Eleanor Holmes Norton …' and 'Hon. Daniel Lipinski …' on one MODS line. Apply the same reviewed joined-line split as ct-79j1 (MODS_JOINED_LINES keyed by package, witness position and line SHA-256, second part at mods:witness[10]/part[2]), with a focused test on the real bytes, then re-run the MODS generation through the reviewed activation path.

