---
id: ct-cxc5
status: open
deps: []
links: [ct-rvma]
created: 2026-11-05T13:10:47Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, source-evidence]
---
# Resolve three existing hearing dates that disagree with printed covers

Independent cover review found three existing date disagreements. Their values are identical in live release e4538f0064e1, the earlier candidate, and final candidate e145d24c389e. These are separate from the repaired later-reposting case in ct-rvma.

| GovInfo package | Current meeting-derived date | Printed cover date |
| --- | --- | --- |
| CHRG-112hhrg68347 | 2011-06-22 | 2011-09-22 |
| CHRG-112hhrg80849 | 2012-07-25 | 2012-06-25 |
| CHRG-113hhrg82590 | 2013-07-10 | 2013-05-09 |

The body hashes and comparisons are retained in `.cache/archive-release/handoffs/cursor-resume-20261105/final-acceptance/acceptance.json`; independently checked cover evidence is in `final-acceptance/independent-covers.json` in the same handoff. The final source is 7f9ebddd2cb632f97bc0214ffd44beaf72b0a5a6.

## Acceptance Criteria

Trace each wrong date to its original meeting or package evidence and correct the responsible rule or source reading. Verify each resulting date against the retained cover and independent meeting evidence. Preserve the multiday hearing control and the CHRG-119hhrg60403 control, whose actual May 15, 2025 hearing date disagrees with a May 14 MODS date. If extraction changes, follow the existing parser-version and selective-reprocessing controls. Add focused regression coverage and an independent wrong-date plant before accepting the repair.

