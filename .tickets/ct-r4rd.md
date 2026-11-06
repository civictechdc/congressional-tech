---
id: ct-r4rd
status: in_progress
deps: []
links: [ct-asdg, ct-n61r, ct-zhta, ct-cjwx, ct-mt0h, ct-db3w]
created: 2026-10-31T07:22:48Z
type: feature
priority: 2
assignee: mikewolfd
external-ref: ss-ikn9
tags: [spicy-regs, meetings, release, layer2]
---

# Compare published meeting details with the equivalent SpicyRegs fields

Researchers and SpicyRegs need the meeting’s Congress, Congress.gov source update time, meeting type and sitting location. The `e145d24c389e` archive already publishes all four. Committee names and URLs resolve through `committees` by `system_code`.

## Root cause and next step

The existing SpicyRegs comparator declares Congress, update time, building and room absent and compares the mixed `meeting_type` field. Compare `congress_gov_meeting_type` to the Congress.gov label. The mixed field also carries House XML codes and remains useful as published.

A narrow comparison against SpicyRegs `37a6ebd4` matched 6,091 event IDs. Selecting the equivalent type field reduced House differences from 1,386 to one. House `119583` lacks a selected archive Congress, source update, label and sitting start. The same comparison found one Congress, six update and two first-start differences, 31 first-building differences and 18 first-room differences. Archive-only values explain 30 building and 17 room differences. Some remaining differences reflect placeholders or whitespace. Sixteen matched House events have multiple sittings, so the first-sitting probe alone cannot settle location parity.

Update the maintained comparator under `ss-ikn9` and reuse the exact inputs with [ct-db3w](ct-db3w.md). Compare equivalent source values, versions and corresponding sittings. Check held detail evidence for `119583` and other residuals before changing a producer. Preserve Congress.gov precedence and House filling of missing fields on a matching sitting, with explicit source states.

## Acceptance Criteria

- Name the archive release, SpicyRegs generation and selected field destinations. Compare Congress, Congress.gov `updateDate`, equivalent type label, building and room by matched event ID. Record evidence-backed differences, including source version, legitimate House fill and unresolved source detail.
- Retain the `ct-cjwx` independent raw proof for Eastern summer and winter times, source precedence, rooms and normalized buildings. Record the selected parser pin and qualified replay or reuse evidence. Check the selected values against the relevant held raw records.
- Keep detail acquisition time in `ct-tbrj` and document keys in `ct-mt0h`. This ticket owns the shared meeting Congress field.

Reuse the [raw sitting tally](../docs/measurements/explorer-raw-sittings-20261101.json) and the qualified parser transition documented in the [November 5 release](../docs/releases/2026-11-05-e145d24c389e.md).

[November 5 root-cause analysis and source evidence](../docs/plans/production-mvp-root-causes-round2-20261105.md).

## Notes

**2026-11-01T20:08:14Z**

Owner decision 2026-11-01: this ticket delivers congress on meetings.parquet, shared with ct-mt0h, which keeps the document-key work.

**2026-11-02T04:01:45Z**

Code on worktree-agent-a704015cc138b456b @ da425206. Review verdict: merge, stay open. Sittings rule owner-approved as Congress.gov first plus House fill. Open: full-run release check, and spicy-regs value agreement.

**2026-11-05T17:11:15Z**

ct-cjwx's remaining House sitting/building comparator and generation trace move here; reuse its merged parser and independent raw comparison. ct-mt0h's Congress field is already published, while matched SpicyRegs value parity remains this ticket's responsibility. Keep source precedence, summer/winter time, rooms/buildings and the delivered release identity in the comparison. Detail-read acquisition time (ct-tbrj), population gaps (ct-db3w/ct-opy0), and document relationship fields (ct-67k1) retain independent meanings even if one pinned comparison serves them.

Consolidation accepted 2026-11-05: absorb ct-cjwx.

User outcome: Finish delivered meeting-field and sitting parity.

Remaining acceptance: Already-merged House parser and retained raw proof; summer/winter time, room/building and source-precedence cases; exact parser/generation trace; pinned SpicyRegs comparison against the delivered release. Reuse qualified parsing rather than replaying it solely for consolidation.

Source evidence and full original criteria remain in: .tickets/ct-r4rd.md:17; .tickets/ct-cjwx.md:15; docs/measurements/explorer-raw-sittings-20261101.json:5; docs/releases/2026-11-05-e145d24c389e.md:18. The superseded records remain available; completed work is reused and unfinished criteria stay with this owner.

**2026-11-05T21:34:21Z**

The pinned SpicyRegs comparator `519ffb308fd798d5d3c42c4d73a72b3248318a26` compares equivalent Congress.gov fields and exact sitting starts against `e145d24c389e` and `37a6ebd4`. Five focused comparator tests passed. Independent reviewer `/root/coverage_acceptance` reproduced 6,091 matches and the same 52 residual IDs. The 30 building and 17 room differences are one-sided populated archive values at matching starts. Two formatting or placeholder cases remain separate. The held `119583` detail is staged, and `338794` has different source update and sitting start values. The retained House summer/winter proof and parser pins are linked in the acceptance and input records. [Pinned comparison](../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/source-coverage/spicyregs-meetings-comparison-final.json) · [Independent acceptance](../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/acceptance/source-coverage/independent-acceptance.md) · [Parser and input pins](../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/source-coverage/source-coverage-freeze-inputs.json)

The Congressional-tech source and acceptance worktrees were archived and pruned after local integration through `eb7bd6a7` and `e6dd3be3`. The separate comparator branch awaits upstream integration under ss-ikn9. Verify `119583` and the remaining residuals against the qualified published archive generation. [Integration handoff](../.cache/archive-release/implementation/production-mvp-round2-20261105T200638Z/acceptance/source-coverage/HANDOFF.md)

**2026-11-06T18:43:09Z**

All independent comparison work is complete locally in commits `9af30d11` and `7f5b0d81`. Against the selected SpicyRegs `37a6` generation, private candidate `720c` agrees on Congress and equivalent type for all 6,096 matched meetings, including raw-confirmed meeting 119583. All 30 building and 17 room differences are supported House fills at matching sitting starts; five newer-source update differences remain explicit. Six focused tests passed as a partial lane, and independent review confirmed the raw values, summer/winter times and wrong-Congress control. The exact inputs, event dispositions and portable upstream patch are retained under `.cache/archive-release/implementation/reviewed-non-news-20261106/ct-r4rd/` with the report `docs/measurements/meeting-field-parity-20261106.md`. This is private-candidate evidence, not final selected-release or live-reader acceptance.

Remaining: original root owns integrating the two CT commits; upstream `ss-ikn9` owns comparator `519ffb30`; `ct-m104` owns the sole final build, deployment, selection and release-bound comparison/readback. Keep the ticket in progress until those acceptance steps pass, using qualified replacement parser evidence where the final source changes.

Independent review is in progress. No final review approval or completed release acceptance is claimed. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-r4rd/REVIEW.md).
