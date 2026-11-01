WITH selected AS (
 SELECT v.record_sha,v.videos
 FROM video_records v
 JOIN youtube_cache_bodies b ON encode(v.record_sha,'hex')=b.record_sha
 WHERE v.status='completed'
), expanded AS (
 SELECT record_sha,unnest(videos) AS v FROM selected
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY v['video_id'] ORDER BY v['handle'],encode(record_sha,'hex')) AS rn FROM expanded
)
SELECT concat('youtube:',r.v['video_id']) AS video_key,
 r.v['handle'] AS handle,
 r.v['channel_id'] AS channel_id,
 d.system_code,
 r.v['title'] AS title,
 r.v['description'] AS source_description,
 arrow_cast(try_cast(r.v['published_at'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS published_at,
 arrow_cast(try_cast(r.v['video_published_at'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS video_published_at,
 r.v['duration_seconds'] AS duration_seconds,
 r.v['available'] AS available,
 r.v['has_caption'] AS has_caption,
 arrow_cast(try_cast(r.v['details_checked_at'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS details_checked_at,
 r.v['stated_event_ids'] AS stated_event_ids,
 r.record_sha
FROM ranked r
LEFT JOIN channel_directory d ON d.handle=r.v['handle']
WHERE r.rn=1
