-- Narrow real endpoint membership; endpoint_key is shared url_key(context_url).
SELECT DISTINCT e.source_id,e.body_sha,e.endpoint_key,e.member_path
FROM source_files f JOIN source_endpoints e USING(source_id)
WHERE f.is_real_file AND e.body_sha IS NOT NULL AND e.endpoint_key IS NOT NULL
