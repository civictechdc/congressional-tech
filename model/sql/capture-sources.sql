WITH kept AS (
 SELECT * FROM capture_source_names n WHERE n.sha256 IS NOT NULL OR NOT EXISTS (
 SELECT 1 FROM capture_source_names b WHERE b.source_url=n.source_url AND b.sha256 IS NOT NULL)
)
SELECT *,encode(sha256(json_array(
 CASE WHEN body_sha IS NOT NULL THEN 'bodies/sha256/'||substr(body_sha,1,2)||'/'||body_sha||'.gz' END,
 filename,source_url)),'hex') AS source_id FROM kept
