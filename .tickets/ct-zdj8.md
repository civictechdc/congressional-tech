---
id: ct-zdj8
status: closed
deps: []
links: []
created: 2026-11-10T19:45:31Z
type: task
priority: 2
assignee: mikewolfd
---
# New recordings cannot be traced to their page from the release's kept evidence

On candidate 77673bfb8fcf (2026-11-10), 83 of 118 new no-meeting YouTube recordings had no row in the kept evidence table publisher_links, though their pages were fetched that day and hold the links as ordinary anchors (youtube.com/watch, youtu.be) and embedded players; 35 others on similar pages do have rows. The gate reports these groups as 'source not traced', and attributing them took a read of raw page bodies (.cache/archive-release/release-20261110b/trace-recordings.json). Find why publisher_links omits these video links, and either keep the link that produced each recording in the evidence or give the gate the page for each new recording, so the group can carry an automatic cause on unattended nights.


## Notes

**2026-11-10T20:38:46Z**

2026-11-10 seen again in release 77673bfb8fcf. Checked on published release 77673bfb8fcf (2026-11-10T20:27:52Z) against 619db5f9e08e with DuckDB on the published tables. 123 new recordings, 118 with no event_ids. As the description says, 83 of the 118 were traced only by a raw read of the day's pages (release-20261110b/trace-recordings.json). The gate group 'empty event_ids; source not traced' shipped with a hand cause. Nothing changed here.

**2026-11-11T14:44:37Z**

validated 2026-11-11, left open: not started; the 77673bfb8fcf gate group 'empty event_ids; source not traced' shipped with a hand cause, and no commit names ct-zdj8.

**2026-11-12T05:40:00Z**

Closed:
- Root cause: `model/sql/publisher-links.sql` joins `resolved_links` targets only against `copy_url_keys` and `source_endpoints` (addresses with a fetched `capture_sources` copy). The 35 YouTube URLs present in `publisher_links` had HTTP fetch attempts in `captures`, whereas the 83 omitted YouTube watch/youtu.be/embed links were never HTTP-fetched themselves and entered `recordings` through `resolved_link_targets -> recording_link_candidates -> recording_video_links`.
- Kept `recording_video_links.parquet` (`['page_body', 'extracted_key']`) in `archive-model/evidence/` (`archive_model.py`), wired `release_comparison.add_evidence` / `recordings` to verify newly eligible linking pages from `recording_video_links.parquet`, and wired `archive_publish.py` + `release_gate.automatic_causes` to trace added no-meeting recordings through `recording_video_links.parquet` (and caption track bodies) to newly captured receipts verified against raw JSONL lines on unattended nights.
