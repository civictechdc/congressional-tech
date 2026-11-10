---
id: ct-syp1
status: in_progress
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


## Notes

**2026-11-10T06:32:22Z**

2026-11-10 branch claude/ct-gate-rules: the comparison now proves the refresh rows itself (release_comparison.cache_churn) and reports them verified, so they need no cause entry on a reviewed or a nightly publish; release_gate's unattended policy ignores exactly those proven groups.

Rule, per matched row. Content columns are every column except the key and the citation columns, by exclusion, so a new column is content until listed (release_comparison.CITATIONS). Today: channels channel_id, system_code, committee_label, role, title, custom_url, uploads_scan_complete, mapping_basis; videos handle, channel_id, system_code, title, source_description, published_at, video_published_at, duration_seconds, available, has_caption, stated_event_ids; recording_matches every column but match_id and source_ref.
- channel: content equal, record_sha present and different, and over all channels its old file went to one new file that came from that old file only.
- video: content equal, the row cites its own channel's file in both releases and that channel passed, details_checked_at equal or later.
- match: content equal, source_ref is video_records: plus that video's record_sha in each release.
A row with any content change proves nothing: its citation change stays in the unverified group. If the two releases' columns or types differ for a table, nothing in it is proven.

Real pair 630164505301 to 619db5f9e08e (investigations/gate-rules-20261110/syp1-real-data.md): proven channels record_sha 119 of 119, recording_matches source_ref 6,621 of 6,621, videos record_sha 67,318 of 67,373, videos details_checked_at 67,064 of 67,119. Still needing a record: title 4, duration 12, description 39, added videos 33, added matches 18, and the record_sha and details_checked_at of the 55 rows those three columns touch (55 each). A plain-Python recount with the file map read from the videos gives the same four counts; 8 values planted on the real candidate (title, duration, description, a hash that is no file, an earlier check time, a channel title, a match citing another file, a match re-pointed) are each left unproven. Whole comparison 3.4 s.

Cannot see: whether the new hash is a real file's or the file holds the published values (the gate reads releases, not raw). Remains: a refresh that also brings new uploads or a one-second duration drift still needs a record for those groups, so a night after a refresh is green only when nothing but citations moved; citing a content hash instead of the file hash (the ticket's other option) would remove the churn at the source and was not done here.
