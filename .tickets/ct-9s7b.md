---
id: ct-9s7b
status: open
deps: []
links: []
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

