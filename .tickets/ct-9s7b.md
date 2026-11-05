---
id: ct-9s7b
status: open
deps: []
links: [ct-o2pr, ct-1i4q, ct-t915, ct-gi01, ct-sulv]
created: 2026-11-02T13:54:36Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [recordings, captions, phase2]
---

# Publish complete Senate caption tracks with one supported production label

People opening captions should get a complete track or subtitle playlist with a supported production label. In baseline `e145d24c389e`, retained analysis counted 1,538 Senate WebVTT track rows across 773 videos and 4,367 duplicate-production body/video pairs across formats, mostly playlists.

## Root cause (2026-11-05)

Track selection has two independent failures. The model can admit a playlist-listed WebVTT segment as a complete track and then choose it because its fetch is newest. Separately, the registry join emits both a generic `caption` match and a more specific `live` or `archive` match for the same fetch. Ranking by production lets both labels survive. In that baseline, `senate:govtaff061726` carries the same playlist hash and same WebVTT hash under both `caption` and `live`.

## Merged repair and release checks

Local `main` includes the playlist producer and release wiring from `2ec1f30d`, `393754ae` and `528b6adb` through merge `18049548`. The model resolves playlist child addresses, excludes listed segments and known placeholders, and ranks one supported label per recording and body.

The record-only backfill ran at `75c99254` and recorded its producer origin alongside the output. All 4,361 completed HLS playlist rows match the intended keys and prior replay payloads. The local verification found zero missing or extra keys and zero rows with an absent or different parser version. In the retained `senate:govtaff061726` check, the model selected the declared live subtitle playlist. [Backfill verification](../.cache/archive-release/implementation/production-mvp-20261105T190929Z/reader-metadata/integration-playlist.verification.json) · [Producer origin](../.cache/archive-release/implementation/production-mvp-20261105T190929Z/reader-metadata/integration-playlist/playlist_records/producer.json) · [Senate track evidence](../.cache/archive-release/implementation/production-mvp-20261105T190929Z/dates-captions-recovery/captions/govtaff/check.json).

After the all-wave hold, the release coordinator owns final input reconciliation, the guarded native import with a two-way comparison, and the segment and label checks on the same combined candidate. Confirm representative tracks through the site and MCP on the selected release. [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md).

## Acceptance Criteria

- In the candidate, a listed segment or placeholder cannot appear as a track. An independently supported subtitle playlist or complete caption body remains. Use the existing native segment and unread-playlist checks on the selected input.
- Each fetched body has one supported `(format, language, production)` per recording. An independently planted complete playlist with conflicting labels fails even when no segment is present. Preserve distinct legitimate tracks and the evidence behind each selected production.
- Prove both behaviors on the same candidate and record representative tracks and the selected release through the existing checks.

## Coordination and evidence

[ct-sulv](ct-sulv.md) retains the original label-overlap finding. [ct-j78x](ct-j78x.md) owns recording-to-meeting associations. The [MVP root-cause plan](../docs/plans/production-mvp-root-causes-20261105.md) traces the original eligibility and label failures and the prior playlist work.

## Notes

**2026-11-02T14:24:04Z**

2026-11-02 red-e1 recount: plan-h's copy of 448651e7 has 773 Senate recordings with segment caption tracks (1,538 track rows), not 1,452; 667 of them point at one 57-byte segment. r1b-e1 doesn't change this.

**2026-11-02T14:38:27Z**

2026-11-02 (lead): impl-r4-c investigation on live 448651e7: 773 Senate recordings carry vtt tracks (1,538 rows), and every one is an HLS segment; 667 point at a 57-byte WEBVTT header with no cues. The right track is the subtitle playlist, already published for 770 of 773. Origin 959c23ee (archive_model.py:731). Folded into the fixed release on branch r4-tracks (stacked on r1b-e1): read m3u8 segment links in a separate module (no readings pin move), anti-join playlist-listed segments and placeholders, native segment_tracks = 0 check. Also checking 765 recordings with the same body under both live and caption productions.

**2026-11-02T15:33:09Z**

2026-11-02 (lead): fix done on r4-tracks (e4ebdddf, 6e495a74; stacked on r1b-e1): a new playlist_records lake table, playlist_uris in parsers/captions.py, the model drops playlist-listed vtt and placeholder bodies, native checks segment_tracks and unread_track_playlists. On live 448651e7 all 773 recordings lose their segment tracks and all 773 keep a subtitle playlist; nothing else changes. Decision: NOT in the fixed release. The new table needs wiring into the daily, backfill, model and publish jobs, publish-model.json, gate 5 and Basin; that is critical-path scope, and the defect is pre-existing, not a regression. Ships in the first release after; keep r4-tracks rebased.

**2026-11-05T17:11:15Z**

Consolidation accepted 2026-11-05: absorb ct-sulv.

User outcome: Deliver truthful recording tracks and production labels together.

Remaining acceptance: Two independent gates: no segment/placeholder used as a complete track; no body assigned conflicting production labels. Include a complete duplicate-labelled playlist plant. Finish daily/backfill/model/catalog/publish wiring; keep ct-j78x package association separate.

Source evidence and full original criteria remain in: .tickets/ct-9s7b.md:24; .tickets/ct-sulv.md:13. The superseded records remain available; completed work is reused and unfinished criteria stay with this owner.

**2026-11-05T20:18:06Z**

Integrated the maintained playlist producer and recording-track selection. A genuine local backfill produced all 4,361 completed current HLS records, matching the intended keys and retained payloads with no missing, extra or duplicate keys. The retained Govtaff case distinguishes the subtitle playlist from its segments. Redirect and unkeyed-parent controls passed. Native import and final reader/publication checks wait for the combined waves.

**2026-11-05T23:55:26Z**

Implementation review: the original segment exclusion, supported production label and recording-ownership fixes are merged and independently accepted; all 4,361 playlist rows are imported. Keep this ticket open for the newly added meeting-level discovery and event 338785 / 938-of-1,553 reconciliation criteria. Those criteria are not established by the original track-selection checks. Preserve the concurrent additions and verify the final release with ct-gi01/ct-m104.
