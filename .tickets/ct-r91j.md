---
id: ct-r91j
status: closed
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


## Notes

**2026-11-11T00:18:36Z**

f6615f13 (claude/dx-reading-evidence) records the readings drift from ct-an6o's lake/versions.py, together with W1's, as equivalence: bundle_version's version_digest(files={}) is unchanged. Measured there: sniff's 32-file closure reaches docspec_client only through retention/__init__.py and weekly_tables, so client plumbing (W1) moved sniff's evidence as well.

**2026-11-11T14:32:38Z**

validated 2026-11-11, left open: not done. reading_version_diagnostics.body_text_evidence still fingerprints the closure from lake/body_text.py (line 73), so the 68-file closure stands; W1 (f6615f13), W4 (030d44b3), W5 (288ba64f) and ct-p394 (a4ec992b) each needed a recorded equivalence this week because of it. The readings drift from ct-an6o was recorded in f6615f13, so that part of the acceptance is met. Remains: narrow the closure (owner's call per decisions-overnight 00:22Z) with its test in test_body_text_derivation.py.

**2026-11-11T15:50:44Z**

Built on claude/dx-narrow-reading-evidence (owner decision 2026-11-11: narrow it to what readers run). 451931a4 has the tests first, in test_body_text_derivation.py: an edit to plumbing no reader runs (client, provenance, versions, tables, weekly_tables) moves no evidence value; an edit to code a reader runs still moves that reader; every file a reader runs on its fixtures is in its evidence. 87c9b3f6 has the change: reading_version_diagnostics.READERS lists, per entry, the reader modules it walks and the dispatcher and producer files it hashes by bytes only; the walk stops at retention/weekly_tables.py; evidence_files owns what is hashed. lake/versions.py is untouched. Files per entry: sniff 33 to 19, readings 57 to 27, body text 68 to 24, the others unchanged. Three plants caught. Remains: the one equivalence re-stamp (sniff, readings and the four body-text readers) after the rebase onto the MODS merge, then doctor. Design note: .cache/archive-release/investigations/docspec-feedback-20261110/refactor/narrow-evidence/ne_design-note.txt

**2026-11-11T23:05:43Z**

Rebased onto origin/main e3b5235b (after MODS merge 78933231, preserving lake/versions.py untouched; tip a356d2a8) and recorded the single equivalence re-stamp in 580b55b8 (cause: the evidence definition changed, ct-r91j; no reader's output can change). Verified field-by-field against origin/main: only workspace_sha256 and locked_sha256 on sniff, readings, pdf_text, html_text, xml_text and warc moved; html, xml, json and html_metadata had zero diffs and all declared versions, limits and fixture samples matched. Post-restamp doctor passed with 0 WARNING lines. Full stacked lane set (.cache/archive-release/lanes-dx-stack-r91j-hhym-fc874b7c, 22:49:02Z to 23:04:55Z): all 6 production-offline shards exit 0 (13,020 passed, 39 skipped) and storage-loopback exit 0 (35 passed).
