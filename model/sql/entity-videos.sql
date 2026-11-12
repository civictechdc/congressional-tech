WITH selected AS (
 SELECT v.record_sha,v.videos,0 AS precedence
 FROM selected_video_records v
 JOIN youtube_cache_bodies b ON encode(v.record_sha,'hex')=b.record_sha
 WHERE v.status='completed' AND v.source='youtube_cache'
 UNION ALL
 -- API videos fill only video IDs no cache lists (unlisted uploads, unprocessed live archives).
 SELECT v.record_sha,v.videos,1 AS precedence
 FROM selected_video_records v
 JOIN youtube_api_bodies b ON encode(v.record_sha,'hex')=b.record_sha
 WHERE v.status='completed' AND v.source='youtube_api'
), channel_handles AS (
 SELECT channel_id,min(handle) AS handle FROM channel_directory WHERE channel_id IS NOT NULL GROUP BY channel_id
), expanded AS (
 SELECT s.record_sha,s.precedence,s.v,CASE WHEN s.precedence=0 THEN s.v['handle'] ELSE h.handle END AS handle
 FROM (SELECT record_sha,precedence,unnest(videos) AS v FROM selected) s
 LEFT JOIN channel_handles h ON s.precedence=1 AND h.channel_id=s.v['channel_id']
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY v['video_id'] ORDER BY precedence,handle,encode(record_sha,'hex')) AS rn
 FROM expanded WHERE handle IS NOT NULL AND handle<>''
)
SELECT concat('youtube:',r.v['video_id']) AS video_key,
 r.handle AS handle,
 r.v['channel_id'] AS channel_id,
 d.system_code,
 nullif(regexp_replace(r.v['title'],'^\s+|\s+$','','g'),'') AS title,
 nullif(regexp_replace(r.v['description'],'^\s+|\s+$','','g'),'') AS source_description,
 arrow_cast(try_cast(r.v['published_at'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS published_at,
 arrow_cast(try_cast(r.v['video_published_at'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS video_published_at,
 r.v['duration_seconds'] AS duration_seconds,
 r.v['available'] AS available,
 r.v['has_caption'] AS has_caption,
 arrow_cast(try_cast(r.v['details_checked_at'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS details_checked_at,
 r.v['stated_event_ids'] AS stated_event_ids,
 r.record_sha
FROM ranked r
LEFT JOIN channel_directory d ON d.handle=r.handle
WHERE r.rn=1
