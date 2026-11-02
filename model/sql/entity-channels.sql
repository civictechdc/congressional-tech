WITH selected AS (
 SELECT v.record_sha,v.channels
 FROM selected_video_records v
 JOIN youtube_cache_bodies b ON encode(v.record_sha,'hex')=b.record_sha
 WHERE v.status='completed'
), expanded AS (
 SELECT record_sha,unnest(channels) AS c FROM selected
), ranked AS (
 SELECT record_sha,c['handle'] AS handle,c['channel_id'] AS channel_id,c['title'] AS title,c['custom_url'] AS custom_url,
  c['uploads_scan_complete'] AS uploads_scan_complete,
  row_number() OVER(PARTITION BY c['handle'] ORDER BY encode(record_sha,'hex')) AS rn
 FROM expanded
)
SELECT d.handle,
 coalesce(d.channel_id,r.channel_id) AS channel_id,
 d.system_code,
 d.committee_label,
 d.role,
 r.title,
 r.custom_url,
 r.uploads_scan_complete,
 cast('curated_directory' AS VARCHAR) AS mapping_basis,
 r.record_sha
FROM channel_directory d
LEFT JOIN ranked r ON r.handle=d.handle AND r.rn=1
