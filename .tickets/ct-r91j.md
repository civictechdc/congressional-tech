---
id: ct-r91j
status: open
deps: []
links: []
created: 2026-11-10T15:41:13Z
type: task
priority: 3
assignee: mikewolfd
tags: [readings, versions]
---
# Reading-version evidence is too wide: an unrelated producer map edit warns on four text readers

From the same equivalence record (2026-11-10, MODS branch commit 374b9f56). The four text parsers hash 68 files, including lake/versions.py, filenames, house_naming and the r2/provenance files, because lake/body_text.py's imports are followed. Editing a producer map in versions.py that no reader executes when deriving a body therefore raises 'reading version evidence changed' for pdf_text, html_text, xml_text and warc and needs a recorded equivalence each time (34 of 34 sampled derivations were identical; the map was read 0 times). Proposed fix: at reading_version_diagnostics.py:75 seed from parsers/body_text.py and retention/sniff.py and hash lake/body_text.py by its bytes only, as the leaf parsers already treat readings.py; 68 files become 34. The readings evidence also drifts on main since ct-an6o's versions.py commits and has no recorded decision.

## Acceptance Criteria

The evidence closure contains only files a reader executes when deriving a body, with a test in test_body_text_derivation.py; an edit to a producer map no longer warns; the readings drift on main has a recorded decision or a re-stamp by its owner.

