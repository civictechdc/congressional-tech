---
id: ct-syp1
status: open
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 2
assignee: mikewolfd
tags: [gate, video, release]
---
# Weekly video cache refresh makes about 74,000 release-gate differences that need a hand-written cause

videos.record_sha (67,373 rows), videos.details_checked_at (67,119), channels.record_sha (119) and recording_matches.source_ref (6,621) all carry or cite the hash of the cache FILE, and the file embeds fetch times, so every refresh rewrites them with no content change. On 2026-11-10 every cache-sourced row equalled the raw file it cites in both releases (0 mismatches; .cache/archive-release/release-20261110/causes/video/README.md). Until this changes every release needs the same proof by hand.

## Acceptance Criteria

Either the gate gives these groups an automatic cause when the cited file changed and every row's content columns are equal, or the rows cite a content hash that ignores fetch times. A release after a cache refresh passes these groups with no hand entry, and a planted content change is still refused.

