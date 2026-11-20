---
id: lps2-qmh5
status: open
deps: []
links: [ct-en4n]
created: 2026-11-20T23:32:58Z
type: bug
priority: 1
assignee: mikewolfd
tags: [explorer, recovery, publication]
---
# Remove unqualified saved copies from usable Explorer downloads

Explorer release 0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3 provides unhidden saved-copy links to 22 structurally damaged PDFs and two State Department HTML error bodies. All 24 originals lack text in the v13 export 7aea7925da324273d16c04e7dd7d53b2a7d3a0ade895f9343063015458d88688. The State document link keys are 359e3b8b6b844d69 and 82867326cf8750a2. The public_copy_control in /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/long-tail-20261120/pdf-source/ct-en4n-reconciliation.json identifies every affected saved SHA and public record. Five hidden recovery associations for four Natural Resources HTML bodies are documented separately.

## Acceptance Criteria

Check the current disposition of all 24 link keys in a successor published release. Offer a qualified replacement where available and report the recovery state for outstanding documents. Preserve original bytes, capture history, legitimate wrapper controls, and document identities. Verify zero unqualified saved bodies offered as usable downloads for these records, and record the release ID and per-record results.


## Notes

**2026-11-20T23:33:34Z**

The November 20 public-copy verification returned exit 1 with 24 counterexamples. The same run confirmed zero inventory originals in the v13 text export. Use the live document and recovery associations in the evidence ledger when testing a successor release.
