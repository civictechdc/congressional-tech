---
id: ct-xt19
status: closed
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


## Notes

**2026-11-02T20:39:51Z**

2026-11-02 ci-poppler c006c4fa (on release-train; train merges it after its lane): poppler 26.06.0 pinned once in test-suites.toml with the source tarball sha256, matching Homebrew's. conda-forge skips 26.06, so CI builds it from source via .github/scripts/install-poppler.sh with a cache (about 95 s cold, 11 s warm). doctor refuses any other pdfinfo -v or pdftotext -v first line (fail-first test). Verified on Actions: all 6 docspec-rs shards computed sniff 01bf09000fce…, the Mac's value. docspec-rs needed no change, since it reuses this repo's setup action. validate-explorer can't finish on Actions until DOCSPEC_RUNTIME_ARTIFACT points at b0342a7, which happens at the main merge (switching it now would break main, which pins the older engine).

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
