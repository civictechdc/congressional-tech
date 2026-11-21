---
id: ct-c2g6
status: closed
deps: []
links: [ct-hz8y]
created: 2026-11-21T05:57:30Z
type: bug
priority: 2
assignee: mikewolfd
tags: [body_text, pdf, ocr]
---
# Restore the missing testing passage on page 151 of the Inspector General report

The public text of the 1,208-page report omits a 25-word passage on physical PDF page 151. The scanned page reports that Endeavors staff did not always test families for COVID-19 when they arrived at or left the hotels. Readers searching or quoting the text miss that finding. Comparing the source image, the saved reading before cleanup and the published text located the omission. The page check now flags it for review.

Use source PDF `251ea1a6d6819b6f01e471cf4d22e924beea8e831c38ae1a4313c6bdd79b01cf` and v13 export `7aea7925da324273d16c04e7dd7d53b2a7d3a0ade895f9343063015458d88688` as the baseline. The review records the original page and both intact column readings. [Published limits](../model/jobs/inputs/body-text-selection-v13/LIMITS.md) · [Omission check](https://github.com/civictechdc/congressional-tech/pull/218)

## Acceptance Criteria

1. Read the original scan and compare the corrected page with both printed columns. Verify the missing words in context, in reading order, exactly once. Record the source, page and selected reading so another reviewer can repeat the comparison.
2. Publish the corrected reading through the existing text release process. Open the exact report from the resulting public text export, locate the passage on page 151 and confirm that the other page texts match the prior release for this page-only repair.
3. Record the release ID and public text identity. Update the published limits for page 151 and preserve the separate known limitation on page 740.

## Notes

**2026-11-21T06:38:58Z**

Two readings of the original scan matched on all 368 word and punctuation tokens on physical page 151. The corrected text contains the full testing passage exactly once. Compared with the prior export, all other 1,207 page texts match byte for byte. The hosted publisher will install the reviewed pair from the v14 selection. Close after reading back the public export. The separate page 740 limitation remains.

**2026-11-21T09:22:33Z**

Readers can now find the full hotel-testing finding on physical page 151 (printed page 5303) of House Report 118–372, Book 4. The corrected passage appears once, in the same order as the two columns on the original scan. An independent reviewer matched all 368 word and punctuation tokens against a transcription of the scan. The check detected both a planted omission and a duplicate. [Corrected page](../model/jobs/inputs/body-text-selection-v14/page-151.txt)

On November 21, the hosted publisher selected release `1fad38cc75ba023aca4af5b2184564869eff9831414c00678310d38370f89eae` and text export `009ec3dc81d3245c955f9379701f6744acad9c981753edca9fdc77d5017d852a` with 326,929 documents. We opened the report from the public export over HTTPS. The original PDF hash is `251ea1a6d6819b6f01e471cf4d22e924beea8e831c38ae1a4313c6bdd79b01cf`. The corrected report text hash is `6973f8979138aa4c9776850ca74d799d1cfbb5d1769a4615da9b8eeb67a1e28d` and the page 151 text hash is `7e086bd148edb62f3034585fe952d217ff422e1c4958e515ca42c3159249baa7`. [Public text release](https://congressional-data.spicygov.ai/derived/body_text/current.json) · [Hosted publication](https://github.com/civictechdc/congressional-tech/actions/runs/44886570824)

Compared with v13 release `0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3`, text export `7aea7925da324273d16c04e7dd7d53b2a7d3a0ade895f9343063015458d88688`, all 1,207 other page texts matched byte for byte. Every later page starts 239 bytes farther into the report. The separate heading issue on page 740 remains recorded. The independent public comparison is in `<main checkout>/.cache/archive-release/fix-downloads-page151-20261121/independent/public-export-review.json`. [Published limits](../model/jobs/inputs/body-text-selection-v14/LIMITS.md) · [Deployed search follow-up](ct-0a35.md)
