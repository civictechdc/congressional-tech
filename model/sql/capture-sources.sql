WITH kept AS (
 SELECT n.* FROM source_body_urls b RIGHT JOIN capture_source_names n ON b.source_url=n.source_url
 WHERE n.sha256 IS NOT NULL OR n.outcome IN ('reference','saved-record') OR b.source_url IS NULL
), keyed AS (
 SELECT n.*,CASE WHEN n.outcome='reference' AND n.sha256 IS NULL AND n.member_path IS NULL
 THEN k.url_key END AS reference_url_key
 FROM source_url_keys k RIGHT JOIN kept n ON k.url=n.source_url AND k.error IS NULL
), associated AS (
 SELECT n.* EXCLUDE(body_sha,filename,source_url,reference_url_key),
 coalesce(t.body_sha,n.body_sha) AS body_sha,
 coalesce(t.filename,n.filename) AS filename,coalesce(t.source_url,n.source_url) AS source_url
 FROM source_reference_targets t RIGHT JOIN keyed n ON t.url_key=n.reference_url_key
)
SELECT *,encode(sha256(json_array(
 CASE WHEN body_sha IS NOT NULL THEN 'bodies/sha256/'||substr(body_sha,1,2)||'/'||body_sha||'.gz' END,
 filename,source_url)),'hex') AS source_id FROM associated
