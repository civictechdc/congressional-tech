-- Only selected tracks and their declared children, preserving declaration order and missing children.
WITH roots AS (
 SELECT video_key,t['body'] AS track_body,t['source_url'] AS root_url,t['suffix'] AS root_suffix,
  t['format'] AS root_format FROM (SELECT video_key,unnest(resources) AS t FROM recording_tracks)
), children AS (
 SELECT record_sha,parser_version,unnest(segments) AS declared_uri,
  unnest(range(1,cast(array_length(segments) AS BIGINT)+1)) AS ordinal
 FROM selected_playlist_records WHERE status='completed'
)
SELECT r.video_key,r.track_body,cast(0 AS BIGINT) AS ordinal,r.root_url AS source_url,
 cast(NULL AS VARCHAR) AS declared_uri,r.track_body AS root_body,r.root_suffix,r.root_format,
 p.parser_version
FROM roots r LEFT JOIN selected_playlist_records p ON r.track_body=p.record_sha AND r.root_format='m3u8'
UNION ALL
SELECT r.video_key,r.track_body,c.ordinal,url_resolve(c.declared_uri,r.root_url) AS source_url,
 c.declared_uri,arrow_cast(NULL,'FixedSizeBinary(32)') AS root_body,cast(NULL AS VARCHAR) AS root_suffix,
 cast(NULL AS VARCHAR) AS root_format,c.parser_version
FROM roots r JOIN children c ON r.track_body=c.record_sha WHERE r.root_format='m3u8'
