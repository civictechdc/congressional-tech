-- One row per video: its current tracks, ranked once. recordings_entity reads it twice (its
-- keys and its join); inlined, the two window sorts over 2.7M track candidates ran per reference.
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
), resolved_tracks AS (
 SELECT coalesce(a.canonical_key,tc.extracted_key) AS video_key,
  arrow_cast(tc.sha256,'FixedSizeBinary(32)') AS body,
  tc.suffix,tc.format,tc.language,tc.production,tc.fetch_url,
  tc.retrieved_at,tc.receipt_key,tc.receipt_line,tc.capture_index
 FROM caption_playlist_bodies p RIGHT JOIN recording_track_candidates tc ON p.record_sha=tc.sha256
 LEFT JOIN video_key_aliases a ON tc.extracted_key=a.alias_key
 WHERE tc.extracted_key IS NOT NULL AND tc.format IS NOT NULL
  AND (tc.format<>'m3u8' OR p.record_sha IS NOT NULL)
), classified_tracks AS (
 -- A specific route or explicit ASR evidence beats a generic label for the same bytes.
 -- Equal evidence keeps the latest fetch. Distinct bodies can still supply different tracks.
 SELECT *,row_number() OVER(PARTITION BY video_key,body ORDER BY
    CASE production WHEN 'asr' THEN 2 WHEN 'live' THEN 1 WHEN 'archive' THEN 1 ELSE 0 END DESC,
    retrieved_at DESC NULLS LAST,receipt_key DESC,receipt_line DESC,capture_index DESC,
    format,language,production) AS body_preference FROM resolved_tracks
), ranked_tracks AS (
 SELECT *,row_number() OVER(
  PARTITION BY video_key,format,language,production
  ORDER BY retrieved_at DESC NULLS LAST,receipt_key DESC,receipt_line DESC,capture_index DESC
 ) AS rn FROM classified_tracks WHERE body_preference=1
), ordered_tracks AS (
 SELECT *,row_number() OVER(
  PARTITION BY video_key
  ORDER BY format ASC,language ASC,production ASC,suffix ASC
 ) AS track_seq
 FROM ranked_tracks WHERE rn=1
), tracks_agg AS (
 SELECT video_key,array_agg(named_struct(
  'body',body,'suffix',suffix,'format',format,'language',language,'production',production
 ) ORDER BY track_seq ASC) AS tracks,
 array_agg(named_struct('body',body,'source_url',fetch_url,'suffix',suffix,'format',format)
  ORDER BY track_seq ASC) AS resources
 FROM ordered_tracks GROUP BY video_key
)
SELECT * FROM tracks_agg
