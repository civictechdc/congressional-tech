-- Positive writer metadata is admission evidence, never a fabricated byte sniff.
-- Either verdict needs every row of a body to qualify, so a body with no qualifying row
-- can never pass. Choosing candidates first keeps this off a GROUP BY over all captures.
WITH candidate_admission_shas AS (
 SELECT DISTINCT sha256 FROM captures WHERE sha256 IS NOT NULL AND (bytes=0 OR (fidelity='saved-text'
  AND media_type IN ('text/vtt','application/vnd.apple.mpegurl','application/x-mpegurl')))
)
SELECT c.sha256 AS body_sha,
CASE WHEN bool_and(coalesce(c.bytes=0,false)) THEN 'empty' WHEN min(c.media_type)='text/vtt' THEN 'vtt' ELSE 'm3u8' END AS format,
'writer_format' AS basis FROM captures c JOIN candidate_admission_shas s ON c.sha256=s.sha256 GROUP BY c.sha256
HAVING bool_and(coalesce(c.bytes=0,false)) OR
(bool_and(coalesce(c.fidelity='saved-text',false)) AND count(c.media_type)=count(*) AND min(c.media_type)=max(c.media_type)
AND min(c.media_type) IN ('text/vtt','application/vnd.apple.mpegurl','application/x-mpegurl'))
