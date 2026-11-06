-- Rank repeated successful fetches only after the selected resource requests have narrowed the scan.
WITH matches AS (
 SELECT r.video_key,r.track_body,r.ordinal,f.sha256 AS body,f.suffix,
  coalesce(CASE WHEN f.body_format IN ('vtt','srt','ttml') THEN f.body_format END,
   CASE WHEN regexp_like(r.source_url,'(?i)[.]vtt(?:[?#]|$)') THEN 'vtt'
        WHEN regexp_like(r.source_url,'(?i)[.]srt(?:[?#]|$)') THEN 'srt'
        WHEN regexp_like(r.source_url,'(?i)[.](?:ttml|dfxp)(?:[?#]|$)') THEN 'ttml' END) AS format,
  f.retrieved_at,f.receipt_key,f.receipt_line,f.capture_index
 FROM caption_resource_requests r JOIN recording_fetch_candidates f ON r.source_url=f.fetch_url WHERE r.ordinal>0
 UNION ALL
 SELECT r.video_key,r.track_body,r.ordinal,f.sha256,f.suffix,
  coalesce(CASE WHEN f.body_format IN ('vtt','srt','ttml') THEN f.body_format END,
   CASE WHEN regexp_like(r.source_url,'(?i)[.]vtt(?:[?#]|$)') THEN 'vtt'
        WHEN regexp_like(r.source_url,'(?i)[.]srt(?:[?#]|$)') THEN 'srt'
        WHEN regexp_like(r.source_url,'(?i)[.](?:ttml|dfxp)(?:[?#]|$)') THEN 'ttml' END) AS format,
  f.retrieved_at,f.receipt_key,f.receipt_line,f.capture_index
 FROM caption_resource_requests r JOIN recording_fetch_candidates f ON r.source_url=f.redirected_from WHERE r.ordinal>0
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY video_key,track_body,ordinal ORDER BY
  retrieved_at DESC NULLS LAST,receipt_key DESC,receipt_line DESC,capture_index DESC) AS preference FROM matches
)
SELECT r.video_key,r.track_body,r.ordinal,r.source_url,r.declared_uri,
 coalesce(r.root_body,m.body) AS body,coalesce(r.root_suffix,m.suffix) AS suffix,
 coalesce(r.root_format,m.format) AS format,r.parser_version,
 CASE WHEN coalesce(r.root_body,m.body) IS NULL THEN 'missing' ELSE 'retained' END AS status
FROM caption_resource_requests r LEFT JOIN ranked m
 ON r.video_key=m.video_key AND r.track_body=m.track_body AND r.ordinal=m.ordinal AND m.preference=1
