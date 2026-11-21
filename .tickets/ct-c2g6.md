---
id: ct-c2g6
status: open
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
