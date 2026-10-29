WITH captured AS (
 SELECT source_id,body_sha,filename,source_url,
 coalesce(max(CASE WHEN is_real_file THEN format END),max(format)) AS format,
 bool_or(is_real_file) AS is_real_file,
 CASE WHEN bool_or(is_real_file) THEN 'document' ELSE min(record_role) END AS record_role,
 min(arrow_cast(CASE WHEN outcome NOT IN ('reference','saved-record') AND import_date IS NULL THEN cast(retrieved_at AS TIMESTAMP WITH TIME ZONE) END,'Timestamp(Microsecond, Some("UTC"))')) AS first_fetched,
 max(arrow_cast(CASE WHEN outcome NOT IN ('reference','saved-record') AND import_date IS NULL THEN cast(retrieved_at AS TIMESTAMP WITH TIME ZONE) END,'Timestamp(Microsecond, Some("UTC"))')) AS last_fetched,
 CASE WHEN count(CASE WHEN outcome NOT IN ('reference','saved-record') AND import_date IS NULL THEN 1 END)=0
 THEN min(CASE WHEN outcome NOT IN ('reference','saved-record') THEN cast(import_date AS DATE) END) END AS in_archive_since,
 coalesce(bool_or(fidelity='exact-bytes'),false) AS exact_bytes,
 max(media_type) AS media_type
 FROM capture_sources GROUP BY source_id,body_sha,filename,source_url
), originals AS (
 SELECT DISTINCT encode(sha256(json_array(cast(NULL AS VARCHAR),f.filename,f.source_url)),'hex') AS source_id,
 cast(NULL AS VARCHAR) AS body_sha,f.filename,f.source_url,cast(NULL AS VARCHAR) AS format,
 false AS is_real_file,cast(NULL AS VARCHAR) AS record_role,
 arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))') AS first_fetched,
 arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))') AS last_fetched,
 cast(NULL AS DATE) AS in_archive_since,
 false AS exact_bytes,
 cast(NULL AS VARCHAR) AS media_type
 FROM current_recoveries r JOIN effective_filenames f ON f.input_id='recovery:'||r.id
) , all_sources AS (
 SELECT * FROM captured UNION ALL SELECT * FROM originals
)
SELECT source_id,body_sha,filename,source_url,max(format) AS format,
 bool_or(is_real_file) AS is_real_file,
 CASE WHEN bool_or(is_real_file) THEN 'document' ELSE min(record_role) END AS record_role,
 min(first_fetched) AS first_fetched,max(last_fetched) AS last_fetched,
 CASE WHEN min(first_fetched) IS NULL THEN min(in_archive_since) END AS in_archive_since,
 coalesce(bool_or(exact_bytes),false) AS exact_bytes,
 max(media_type) AS media_type
FROM all_sources GROUP BY source_id,body_sha,filename,source_url
