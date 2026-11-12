-- Derive recordings.event_ids from recording_matches_export, the single owner of video-to-meeting links (ct-yizl).
WITH match_links AS (
 SELECT video_key,status,decision,unnest(meeting_links) AS link
 FROM recording_matches_export
 WHERE video_key IS NOT NULL AND meeting_links IS NOT NULL
), matched_events AS (
 SELECT DISTINCT video_key,link['event_id'] AS event_id
 FROM match_links
 WHERE link['scope']='event'
  AND link['event_id'] IS NOT NULL
  AND status IN ('asserted','claimed','decided')
  AND coalesce(decision,'') NOT IN ('no_video_found','not_public')
), all_keys AS (
 SELECT DISTINCT video_key FROM recordings_entity WHERE video_key IS NOT NULL
 UNION
 SELECT DISTINCT video_key FROM matched_events WHERE video_key IS NOT NULL
), events_agg AS (
 SELECT video_key,array_sort(array_distinct(array_agg(event_id))) AS event_ids
 FROM matched_events
 GROUP BY video_key
)
SELECT k.video_key,
 coalesce(e.event_ids,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')) AS event_ids,
 coalesce(re.tracks,array_slice(make_array(named_struct(
  'body',arrow_cast(NULL,'FixedSizeBinary(32)'),
  'suffix',cast(NULL AS VARCHAR),
  'format',cast(NULL AS VARCHAR),
  'language',cast(NULL AS VARCHAR),
  'production',cast(NULL AS VARCHAR)
 )),1,0)) AS tracks
FROM recordings_entity re
RIGHT JOIN (events_agg e RIGHT JOIN all_keys k ON e.video_key=k.video_key) ON re.video_key=k.video_key
