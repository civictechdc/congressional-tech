-- Derive recordings.event_ids from recording_matches_export (ct-yizl) and classify
-- recording_scope (full, excerpt, unknown) from curated decisions and video metadata (ct-ywz2).
WITH match_links AS (
 SELECT video_key,basis,status,decision,recording_scope,unnest(meeting_links) AS link
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
), curated_scopes AS (
 SELECT video_key,
  CASE WHEN bool_or(recording_scope='full') THEN 'full'
       WHEN bool_or(recording_scope='excerpt') THEN 'excerpt' END AS curated_scope
 FROM recording_matches_export
 WHERE video_key IS NOT NULL AND basis='curated' AND status='decided'
  AND recording_scope IN ('full','excerpt')
 GROUP BY video_key
), video_signals AS (
 SELECT k.video_key,v.duration_seconds,
  regexp_like(coalesce(v.title,''),'(?i)(?:\b(?:opening|openings|closing)\s+(?:statement|remarks|at\b|on\b)|\bopener\b|\b(?:statement|remarks)\s+(?:at|on|from)\s+(?:a\s+|the\s+|joint\s+|subcommittee\s+|full\s+committee\s+)*(?:hearing|markup)\b|\b(?:question\s+line|questions?\s+(?:to\s+)?(?:witnesses|panel)|q\s*&\s*a)\b|\bhearing\s+highlights\b|\bpool\s+video\b|\bclip\b|\bdelivers?\s+(?:opening\s+statement|(?:witness\s+)?testimony)\b|\bdelivering\s+witness\s+testimony\b|,\s*testimony\s*$|\btestimony\s+at\s+.*\bhearing\b|\btestifies\s+(?:on|about|at)\b|\bpraises\b|\bgrills\b|\bwarns\s+of\b)') AS is_excerpt_title,
  regexp_like(coalesce(v.title,''),'(?i)(?:\b(?:markup|business\s+meeting|organizational\s+meeting|subcommittee\s+assignments|full\s+committee\s+meeting|views\s*(?:&|and)\s*estimates|eventid\s*=\s*[0-9]+)\b|^hearing\s*:)') AS is_full_title
 FROM all_keys k
 JOIN videos_export v ON v.video_key=k.video_key
), video_scopes AS (
 SELECT video_key,
  CASE
   WHEN duration_seconds IS NULL OR duration_seconds<=0 THEN 'unknown'
   WHEN duration_seconds<3600 AND is_excerpt_title THEN 'excerpt'
   WHEN duration_seconds<300 AND NOT is_full_title THEN 'excerpt'
   WHEN duration_seconds>=900 OR is_full_title THEN 'full'
   ELSE 'unknown'
  END AS video_scope
 FROM video_signals
)
SELECT k.video_key,
 coalesce(e.event_ids,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')) AS event_ids,
 coalesce(re.tracks,array_slice(make_array(named_struct(
  'body',arrow_cast(NULL,'FixedSizeBinary(32)'),
  'suffix',cast(NULL AS VARCHAR),
  'format',cast(NULL AS VARCHAR),
  'language',cast(NULL AS VARCHAR),
  'production',cast(NULL AS VARCHAR)
 )),1,0)) AS tracks,
 coalesce(cs.curated_scope,vs.video_scope,'unknown') AS recording_scope
FROM curated_scopes cs
RIGHT JOIN (
 video_scopes vs
 RIGHT JOIN (
  recordings_entity re
  RIGHT JOIN (events_agg e RIGHT JOIN all_keys k ON e.video_key=k.video_key)
  ON re.video_key=k.video_key
 ) ON vs.video_key=k.video_key
) ON cs.video_key=k.video_key
