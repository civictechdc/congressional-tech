---
id: ct-qmh5
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

Explorer release `0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3` lists 26 affected records by default. Their detail pages and five additional hidden detail pages offer unqualified saved copies. All 31 records lack text for the affected saved body in v13 export `7aea7925da324273d16c04e7dd7d53b2a7d3a0ade895f9343063015458d88688`.

| Affected records | In default list | Detail offers saved copy |
| --- | ---: | ---: |
| Damaged PDFs | 22 | 22 |
| State Department HTML error payloads | 2 | 2 |
| Linked State Department archive wrappers | 2 | 2 |
| Natural Resources HTML errors at five document targets | 0 | 5 |
| Total | 26 | 31 |

State payload link keys `359e3b8b6b844d69` and `82867326cf8750a2` correspond to wrappers `6eea94ddc3e78724` and `b6aaf0d8fdba71e2`, respectively. Check all four Explorer records and keep one recovery decision per payload. The hidden Natural Resources keys are `85afe0532f6c8e0b`, `a3002f39e37a6384`, `90bd27046786ab4e`, `8b408d366abfb89d` and `e8c6aced18461017`. The last two share one saved body.

The verification ledger pinned by `docs/plans/ocr-source-recovery-inventory.json` identifies all 31 link keys and saved hashes under `public_copy_control.records`. Explorer lists unhidden records by default. On a detail page, a primary saved body enables the primary and alternate links. A recovery with different bytes has its own link, including when the primary is absent. The five Natural Resources pages and the Walling page (`20568d1abba1b309`) each reference their invalid body as both primary and recovery. Clearing those primaries still leaves six recovery downloads. Walling already counts among the 22 damaged PDF pages.

## Acceptance Criteria

1. Resolve every one of the 31 link keys in a successor published release. Record the release ID, document identity, default-list visibility, detail-page download availability and the qualification of any saved replacement. Document the disposition of missing or reassociated records.
2. Verify zero default-list records exposing an unqualified saved copy and zero detail pages offering one. Check primary, alternate and recovery links, including the five hidden details. Count each detail link key once. Repeat with invalid primaries cleared to confirm the guard still detects surviving links.
3. Offer qualified replacements where available and report outstanding recovery per payload and document target. Preserve the original bytes, receipts, legitimate wrapper controls and document identities. Return the per-record release evidence to ct-en4n.

## Notes

**2026-11-20T23:33:34Z**

The November 20 public-copy verification returned exit 1 with 24 counterexamples. The same run confirmed zero inventory originals in the v13 text export. Use the live document and recovery associations in the evidence ledger when testing a successor release.

**2026-11-20T23:54:56Z**

The figure of 24 above counted unhidden inventory originals in the first pass. The corrected guard includes the two State wrappers and measures detail downloads on hidden rows. The current baseline is 26 visible records and 31 detail downloads.

**2026-11-21T05:58:20Z**

The public release pointer still named `0e7084cde775` on November 21. The verified baseline for that release is 26 affected records in the default list and 31 distinct detail pages offering a bad copy. Fix the download choices, keep each usable replacement, and check all 31 pages on the next release containing the fix. Include the six pages where clearing the primary copy alone leaves a bad recovery download. Return the per-page results to [the source audit](ct-en4n.md).
