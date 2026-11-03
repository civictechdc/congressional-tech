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
# Senate recordings use one HLS caption segment as their caption track

impl-e1 2026-11-02: in 448651e7, 1,452 Senate recordings use a single VTT segment as their caption track. Pre-existing. Annex §2 says a streamed track's segment files are not tracks; the track should be the playlist, or the segments joined.

## Acceptance Criteria

No segment file is published as a track; Senate caption tracks point to the playlist or a complete caption body; a native check refuses a segment track.


## Notes

**2026-11-02T14:24:04Z**

2026-11-02 red-e1 recount: plan-h's copy of 448651e7 has 773 Senate recordings with segment caption tracks (1,538 track rows), not 1,452; 667 of them point at one 57-byte segment. r1b-e1 doesn't change this.

**2026-11-02T14:38:27Z**

2026-11-02 (lead): impl-r4-c investigation on live 448651e7: 773 Senate recordings carry vtt tracks (1,538 rows), and every one is an HLS segment; 667 point at a 57-byte WEBVTT header with no cues. The right track is the subtitle playlist, already published for 770 of 773. Origin 959c23ee (archive_model.py:731). Folded into the fixed release on branch r4-tracks (stacked on r1b-e1): read m3u8 segment links in a separate module (no readings pin move), anti-join playlist-listed segments and placeholders, native segment_tracks = 0 check. Also checking 765 recordings with the same body under both live and caption productions.

**2026-11-02T15:33:09Z**

2026-11-02 (lead): fix done on r4-tracks (e4ebdddf, 6e495a74; stacked on r1b-e1): a new playlist_records lake table, playlist_uris in parsers/captions.py, the model drops playlist-listed vtt and placeholder bodies, native checks segment_tracks and unread_track_playlists. On live 448651e7 all 773 recordings lose their segment tracks and all 773 keep a subtitle playlist; nothing else changes. Decision: NOT in the fixed release. The new table needs wiring into the daily, backfill, model and publish jobs, publish-model.json, gate 5 and Basin; that is critical-path scope, and the defect is pre-existing, not a regression. Ships in the first release after; keep r4-tracks rebased.
