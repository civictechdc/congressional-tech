WITH unnested_meeting_videos AS (
 SELECT event_id,unnest(videos) AS v FROM meetings_resolved WHERE videos IS NOT NULL
), flat_meeting_videos AS (
 SELECT event_id,v['url'] AS video_url,nullif(trim(v['video_key']),'') AS explicit_key
 FROM unnested_meeting_videos
), raw_meeting_videos AS (
 SELECT m.event_id,m.video_url AS url,m.explicit_key,
  min(regexp_replace((regexp_match(m.video_url,rs.pattern))[1],'^(.+)$',rs.key_template)) AS extracted_key
 FROM flat_meeting_videos m
 LEFT JOIN recording_sources rs ON rs.kind='video_url' AND m.video_url IS NOT NULL AND regexp_like(m.video_url,rs.pattern)
 GROUP BY m.event_id,m.video_url,m.explicit_key
), page_video_links AS (
 SELECT DISTINCT l.page_body,l.context_url,l.target_url,
  regexp_replace((regexp_match(l.target_url,rs.pattern))[1],'^(.+)$',rs.key_template) AS extracted_key
 FROM resolved_link_targets l
 JOIN recording_sources rs ON rs.kind='video_url' AND l.target_url IS NOT NULL AND regexp_like(l.target_url,rs.pattern)
), page_meetings AS (
 SELECT encode(body_sha,'hex') AS page_body,unnest(named_meetings) AS event_id
 FROM page_facts WHERE status='completed' AND named_meetings IS NOT NULL
 UNION
 SELECT DISTINCT c.body_sha AS page_body,try_cast(a.meeting_key AS BIGINT) AS event_id
 FROM source_annotation_addresses a
 JOIN capture_source_contexts c ON a.source_id=c.source_id
 WHERE try_cast(a.meeting_key AS BIGINT) IS NOT NULL AND c.body_sha IS NOT NULL
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
 FROM page_video_links pvl
 LEFT JOIN page_meetings pm ON pvl.page_body=pm.page_body
 LEFT JOIN video_key_aliases a ON pvl.extracted_key=a.alias_key
 WHERE pvl.extracted_key IS NOT NULL
), candidate_fetches AS (
 SELECT g.receipt_key,g.receipt_line,g.capture_index,g.sha256,
  coalesce(g.stored_suffix,'.gz') AS suffix,
  coalesce(g.sniffed_format,CASE lower(split_part(g.media_type,';',1)) WHEN 'text/vtt' THEN 'vtt' WHEN 'application/vnd.apple.mpegurl' THEN 'm3u8' WHEN 'application/x-mpegurl' THEN 'm3u8' END) AS body_format,
  coalesce(g.url,g.requested_url,g.context_url) AS fetch_url,
  arrow_cast(try_cast(g.retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS retrieved_at
 FROM captures g
 WHERE g.mode='fetch' AND g.complete AND g.outcome IN ('stored','unchanged') AND g.http_status BETWEEN 200 AND 299
  AND g.sha256 IS NOT NULL AND coalesce(g.url,g.requested_url,g.context_url) IS NOT NULL
), track_candidates AS (
 SELECT cf.receipt_key,cf.receipt_line,cf.capture_index,cf.sha256,cf.suffix,cf.fetch_url,cf.retrieved_at,
  regexp_replace((regexp_match(cf.fetch_url,vu.pattern))[1],'^(.+)$',vu.key_template) AS extracted_key,
  coalesce(
   CASE WHEN cf.body_format IN ('vtt','srt','m3u8','ttml') THEN cf.body_format END,
   tf.format,
   vu.format
  ) AS format,
  coalesce(
   lower(nullif((regexp_match(cf.fetch_url,'(?i)[?&](?:t?lang)=([a-z]{2,3}(?:-[a-z0-9]+)?)'))[1],'')),
   lower(nullif((regexp_match(cf.fetch_url,'(?i)/(?:subtitles|captions|cc)/([a-z]{2,3})(?:/|[._-])'))[1],'')),
   vu.default_language,tf.default_language,'en'
  ) AS language,
  coalesce(
   CASE WHEN regexp_like(cf.fetch_url,'(?i)[?&](?:kind|caps)=asr(?:[&#]|$)') THEN 'asr' END,
   vu.default_production,tf.default_production,'caption'
  ) AS production
 FROM candidate_fetches cf
 JOIN recording_sources vu ON vu.kind='video_url' AND regexp_like(cf.fetch_url,vu.pattern)
 LEFT JOIN recording_sources tf ON tf.kind='track_format' AND regexp_like(cf.fetch_url,tf.pattern)
 WHERE NOT EXISTS (
  SELECT 1 FROM recording_sources ex WHERE ex.kind='segment_exclusion' AND regexp_like(cf.fetch_url,ex.pattern)
 )
), resolved_tracks AS (
 SELECT coalesce(a.canonical_key,tc.extracted_key) AS video_key,
  arrow_cast(tc.sha256,'FixedSizeBinary(32)') AS body,
  tc.suffix,tc.format,tc.language,tc.production,
  tc.retrieved_at,tc.receipt_key,tc.receipt_line,tc.capture_index
 FROM track_candidates tc
 LEFT JOIN video_key_aliases a ON tc.extracted_key=a.alias_key
 WHERE tc.extracted_key IS NOT NULL AND tc.format IS NOT NULL
), ranked_tracks AS (
 SELECT *,row_number() OVER(
  PARTITION BY video_key,format,language,production
  ORDER BY retrieved_at DESC NULLS LAST,receipt_key DESC,receipt_line DESC,capture_index DESC
 ) AS rn FROM resolved_tracks
), tracks_agg AS (
 SELECT video_key,array_agg(named_struct(
  'body',body,'suffix',suffix,'format',format,'language',language,'production',production
 ) ORDER BY format,language,production,suffix) AS tracks
 FROM ranked_tracks WHERE rn=1 GROUP BY video_key
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
