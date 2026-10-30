WITH unnested_meeting_videos AS (
 SELECT event_id,unnest(videos) AS v FROM meetings_resolved WHERE videos IS NOT NULL
), flat_meeting_videos AS (
 SELECT event_id,v['url'] AS video_url,nullif(trim(v['video_key']),'') AS explicit_key
 FROM unnested_meeting_videos
), raw_meeting_videos AS (
 SELECT m.event_id,m.video_url AS url,m.explicit_key,
  min(regexp_replace((regexp_match(m.video_url,rs.pattern))[1],'^(.+)$',rs.key_template)) AS extracted_key
 FROM flat_meeting_videos m
 LEFT JOIN recording_url_sources rs ON m.video_url IS NOT NULL AND regexp_like(m.video_url,rs.pattern)
 GROUP BY m.event_id,m.video_url,m.explicit_key
), video_key_aliases AS (
 SELECT extracted_key AS alias_key,min(explicit_key) AS canonical_key
 FROM raw_meeting_videos
 WHERE extracted_key IS NOT NULL AND explicit_key IS NOT NULL AND extracted_key<>explicit_key
 GROUP BY extracted_key
), meeting_video_events AS (
 SELECT coalesce(a.canonical_key,rmv.explicit_key,rmv.extracted_key) AS video_key,rmv.event_id
 FROM raw_meeting_videos rmv
 LEFT JOIN video_key_aliases a ON coalesce(rmv.explicit_key,rmv.extracted_key)=a.alias_key
 WHERE coalesce(rmv.explicit_key,rmv.extracted_key) IS NOT NULL
 UNION
 SELECT coalesce(a.canonical_key,pvl.extracted_key) AS video_key,pm.event_id
 FROM recording_video_links pvl
 LEFT JOIN recording_page_meetings pm ON pvl.page_body=pm.page_body
 LEFT JOIN video_key_aliases a ON pvl.extracted_key=a.alias_key
 WHERE pvl.extracted_key IS NOT NULL
), resolved_tracks AS (
 SELECT coalesce(a.canonical_key,tc.extracted_key) AS video_key,
  arrow_cast(tc.sha256,'FixedSizeBinary(32)') AS body,
  tc.suffix,tc.format,tc.language,tc.production,
  tc.retrieved_at,tc.receipt_key,tc.receipt_line,tc.capture_index
 FROM recording_track_candidates tc
 LEFT JOIN video_key_aliases a ON tc.extracted_key=a.alias_key
 WHERE tc.extracted_key IS NOT NULL AND tc.format IS NOT NULL
), ranked_tracks AS (
 SELECT *,row_number() OVER(
  PARTITION BY video_key,format,language,production
  ORDER BY retrieved_at DESC NULLS LAST,receipt_key DESC,receipt_line DESC,capture_index DESC
 ) AS rn FROM resolved_tracks
), ordered_tracks AS (
 SELECT *,row_number() OVER(
  PARTITION BY video_key
  ORDER BY format ASC,language ASC,production ASC,suffix ASC
 ) AS track_seq
 FROM ranked_tracks WHERE rn=1
), tracks_agg AS (
 SELECT video_key,array_agg(named_struct(
  'body',body,'suffix',suffix,'format',format,'language',language,'production',production
 ) ORDER BY track_seq ASC) AS tracks
 FROM ordered_tracks GROUP BY video_key
), all_keys AS (
 SELECT DISTINCT video_key FROM meeting_video_events WHERE video_key IS NOT NULL
 UNION
 SELECT DISTINCT video_key FROM tracks_agg WHERE video_key IS NOT NULL
), events_agg AS (
 SELECT video_key,array_sort(array_distinct(array_agg(event_id))) AS event_ids
 FROM meeting_video_events WHERE video_key IS NOT NULL AND event_id IS NOT NULL
 GROUP BY video_key
)
SELECT k.video_key,
 coalesce(e.event_ids,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')) AS event_ids,
 coalesce(t.tracks,array_slice(make_array(named_struct(
  'body',arrow_cast(NULL,'FixedSizeBinary(32)'),
  'suffix',cast(NULL AS VARCHAR),
  'format',cast(NULL AS VARCHAR),
  'language',cast(NULL AS VARCHAR),
  'production',cast(NULL AS VARCHAR)
 )),1,0)) AS tracks
FROM all_keys k
LEFT JOIN events_agg e ON k.video_key=e.video_key
LEFT JOIN tracks_agg t ON k.video_key=t.video_key
