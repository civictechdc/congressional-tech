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

# Correct three hearing dates that disagree with the printed covers

Researchers should see when the printed proceeding occurred and still be able to follow related meeting records. In baseline release `e145d24c389e`, three document dates disagree with hash-matched covers. In these cases, the retained MODS dates agree with the covers.

| GovInfo package | e145 date | Printed cover |
| --- | --- | --- |
| `CHRG-112hhrg68347` | 2011-06-22 | 2011-09-22 |
| `CHRG-112hhrg80849` | 2012-07-25 | 2012-06-25 |
| `CHRG-113hhrg82590` | 2013-07-10 | 2013-05-09 |

## Root cause (2026-11-05)

`component-meeting-links.sql` takes the earliest date across broad component links. `document-normalized.sql` uses that date as a document-date fallback.

- `68347` is listed by June event `103916` and September event `103921`. Only `103921` publishes the print as a vetted transcript. The fallback takes the June attachment date.
- `80849` and `82590` each have one attached event, `100054` and `101108` respectively. The retained Congress.gov and House records agree on the attached meeting's date and list the print. The cover and MODS establish a different print date. The publisher's reason for each attachment remains unknown.

The evidence identifies a document-date selection error. The linked events have their own dates, which are independently supported by their retained records.

## Merged repair and release checks

Local `main` includes `315145ca` through merge `18049548`. The model selects the vetted September event for `68347` and the corroborated print dates for the other two exact bodies. It reuses the retained readings.

The native cover check matched all three corrected dates and retained all four meeting links and their event dates. It rejected all four planted wrong dates, including the May 14 MODS value for `CHRG-119hhrg60403`, whose cover reads May 15. The multiday and later-repost controls passed. [Cover evidence](../.cache/archive-release/implementation/production-mvp-20261105T190929Z/dates-captions-recovery/covers/check.json).

After the all-wave hold, the release coordinator owns verification of the dates and attachments in the combined candidate and selected release. The broader ambiguous-print fallback remains open. [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md).

## Acceptance Criteria

- Verify the three date values against the retained covers and independent meeting evidence. Retain the two June and September document links for `68347` and preserve both other attachments.
- Keep the multiday control and `CHRG-119hhrg60403`, whose May 15, 2025 cover contradicts its May 14 MODS date. Add an independently checked wrong-date plant.
- Reuse accepted source readings for a selection-only change. If extraction changes, follow the existing parser pin and selective replay controls. Verify the resulting date in the selected release.

## Coordination and evidence

Use the exact body hashes and cover checks under `.cache/archive-release/handoffs/cursor-resume-20261105/final-acceptance/` and the [MVP root-cause plan](../docs/plans/production-mvp-root-causes-20261105.md). Preserve the later-reposting repair in [ct-rvma](ct-rvma.md). Coordinate release verification with [ct-m94a](ct-m94a.md), which qualifies dates from URL aliases.

## Notes

**2026-11-05T20:18:06Z**

Integrated three exact-body, cover-supported hearing-date corrections through the existing date decision owner: CHRG-112hhrg68347, CHRG-112hhrg80849 and CHRG-113hhrg82590. Existing multi-day and named contrary controls remain intact. Retained reader checks passed. The combined candidate must verify the final date changes before publication; the full build is held for all waves.
