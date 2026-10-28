-- Positive writer metadata is admission evidence, never a fabricated byte sniff.
SELECT sha256 AS body_sha,
CASE WHEN bool_and(coalesce(bytes=0,false)) THEN 'empty' WHEN min(media_type)='text/vtt' THEN 'vtt' ELSE 'm3u8' END AS format,
'writer_format' AS basis FROM captures WHERE sha256 IS NOT NULL GROUP BY sha256
HAVING bool_and(coalesce(bytes=0,false)) OR
(bool_and(coalesce(fidelity='saved-text',false)) AND count(media_type)=count(*) AND count(DISTINCT media_type)=1
AND min(media_type) IN ('text/vtt','application/vnd.apple.mpegurl','application/x-mpegurl'))
