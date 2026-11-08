---
id: ct-ri0x
status: closed
deps: []
links: [ct-xt19, ct-zpbl]
created: 2026-11-08T13:54:03Z
type: chore
priority: 3
assignee: mikewolfd
tags: [pdf, dev-environment]
---
# Move the Poppler pin from 26.06.0 to 26.10.0 after a sample check

Homebrew moved this Mac's poppler to 26.10.0 on 2026-11-03 (it was never brew-pinned), so doctor refuses it and local test runs prepend .cache/poppler/26.06.0/bin to PATH. Owner decision 2026-11-08: plan the upgrade. Since ct-zpbl, readings declare tool versions, so a move needs a bounded equivalence review, not a re-read of every sniff reading. Steps: run a bounded PDF sample, including the sniff fallback path for PDFs without %%EOF in their last 8 KB, through pdfinfo and pdftotext 26.06.0 and 26.10.0 and compare; record the equivalence decision or a deliberate version bump (docs/development.md#reading-version-changes); then move the pin in test-suites.toml (source tarball sha256), .github/scripts/install-poppler.sh and doctor's fail-first test; verify an Actions run; then brew pin poppler. No known fix in 26.10 is needed; this is upkeep.


## Notes

**2026-11-08T17:16:49Z**

2026-11-08 closed: 466-file stratified equivalence sample showed 0 reading differences (.cache/archive-release/investigations/poppler-26.10-20261108/; independent 15-file recheck agreed); pin moved in 2e261196 (from 44d19e2a) with a recorded decision (docs/measurements/ct-ri0x-poppler-26.10-20261108.md). producer_proof answers legacy sniff -v with each commit's own Poppler pin (bee5fd97). Actions built 26.10 from source and validate-explorer is green on bee5fd97 (run 42502108566). brew pin poppler applied on this Mac.
