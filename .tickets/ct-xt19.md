---
id: ct-xt19
status: open
deps: []
links: [ct-zpbl]
created: 2026-11-02T19:55:03Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [ci, versions]
---
# Pin poppler 26.06 everywhere so the sniff stamp matches across Mac, CI and runners

Owner decision 2026-11-02: the same PDF tools everywhere, and do whatever is fast. sniff_version (retention/sniff.py:29) hashes five code files, pypdf and lxml versions, the first line of pdfinfo -v and pdftotext -v (pdf_tools.reader_versions), and the whole uv.lock. This Mac's Homebrew poppler is 26.06.0; ubuntu-24.04's apt poppler-utils is 24.02. On Linux the registry's sniff entry (current 01bf0900, proven here) fails with 'Compatible version names a superseded pin' (docspec-rs CI run 41506139189: 252 + 42 tests), and runners would treat ~1M sniff readings as stale. Sniff calls the PDF tools only for PDFs without %%EOF in their last 8 KB. Not on the Mac release path. Longer-term fix: the declared-version design (ct-zpbl) records the tool version on each reading instead of in the stamp.

## Acceptance Criteria

One committed poppler pin; CI and hosted jobs install exactly it (docspec-rs CI too); doctor refuses a mismatch, with a fail-first test; an Actions run computes sniff 01bf0900…

