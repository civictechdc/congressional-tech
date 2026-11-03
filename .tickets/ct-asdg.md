---
id: ct-asdg
status: closed
deps: []
links: [ct-r4rd, ct-gi01]
created: 2026-11-02T04:01:45Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [model, meetings, phase2]
---
# False rescheduled_to: Rescheduled does not mean moved

review-c-explorer: 791 of 956 Rescheduled meetings have their own video or transcript. 106383 (own video, Part I to Part II) and 112524 (own transcript, witnesses) are wrong. Cause: old.stated ignores own evidence, and title_key merges parts.

## Acceptance Criteria

entity-meetings.sql is fixed before publishing, checked against raw per row.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): The meeting's own recording decides; transcript jackets are not evidence (Congress.gov lists same-day jackets from other hearings). Expected 46 links to 83, with 4 removed (106383, 112524, 104049, 106136). Title keys keep Part/Day. impl-f.

**2026-11-02T13:22:51Z**

2026-11-02 impl-f (r1b-f, 12 commits): rescheduled_to 46 to 82: 64 supported, 6 ambiguous (reworded titles); 4 removed, 40 added; title keys keep Part/Day.

**2026-11-02T13:43:11Z**

2026-11-02 green-f: 46 to 82 reproduces, but 116450 to 116562 is wrong. Raw shows its own transcript (HHRG-118-VR09-Transcript-20231108.pdf), a witness list and 14 witnesses, and the twin is a Markup. impl-f's raw check passed it because it reused the rule under test. Sent back: held-evidence blocks a reschedule, the check is judged independently, and all 82 are re-checked.

**2026-11-03T22:53:34Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
