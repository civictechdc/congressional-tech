---
id: ct-syp1
status: in_progress
deps: []
links: [ct-xyo9]
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

**2026-11-10T07:39:16Z**

2026-11-10 after the independent review (investigations/gate-rules-20261110/review/REVIEW.md), three fixes on top:
1. details_checked_at is bounded above. A verified row's check time is equal, or later than the live value and not later than the moment of comparison (the gate's own clock, passed to compare as now and written to the report as compared_at). The reviewer's E4 and P6 (every check date set to 2099) now leave every video unverified.
2. A new file hash must be cited nowhere in the live release (channels or videos). Two files swapped (P4e) and rows citing another channel's old file (P4d) now verify nothing; the docstring said so before and the code did not.
3. The limit, stated in the docstring and docs/releases/README.md: the comparison is self-consistency of what the candidate says about itself and reads no file; a made-up hash applied consistently is verified there. The causes are renamed to what is checked (only the file citation moved; citation follows the video's record_sha), and the groups carry a citation_only flag so the unattended policy no longer matches cause strings from another module. For the unattended path the gate now checks the hash against something the candidate does not control: release_gate.cited_files_are_new looks up every record_sha the candidate cites for the first time in the capture table; each must be a captured body and every receipt holding it must be absent from the live release's receipt set, else the night refuses (E1, every hash made up: 52 reasons, 'is not a body in the capture table'). The empty-receipt-set refusal now comes before the nothing-to-prove return for these groups.

Real pair (investigations/gate-rules-20261110/review-syp1-real-data.md): the verified counts are unchanged (119, 6,621, 67,318, 67,064). cited_files_are_new run with the real function and the pinned engine on the candidate's capture evidence (4,176,147 rows) and the live release's own receipt list: 52 newly cited files, all 52 are captured bodies, in 156 receipts under pipeline-data/2026-11-08, none in the live set; no reason returned. All five reviewer plants on the real live release are refused.

Still not checked: the raw receipt line for a cited file (the capture mapping is trusted for the hash), and whether the file holds the published values. A reviewed publish does not run the capture-table check as a refusal; it has the reviewer. The reviewer's note stands that 18 videos (17 API records) cite a file that is not their channel's: when those move, they are not verified and need a person.
