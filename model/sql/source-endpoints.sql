SELECT DISTINCT c.source_id,c.body_sha,k.url_key AS endpoint_key,c.member_path
FROM model_url_keys k JOIN capture_source_contexts c ON c.context_url=k.url
WHERE k.error IS NULL AND c.outcome NOT IN ('reference','saved-record')
