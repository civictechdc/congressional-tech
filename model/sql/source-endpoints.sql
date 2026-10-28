SELECT DISTINCT c.source_id,c.body_sha,k.url_key AS endpoint_key,c.member_path
FROM capture_sources c JOIN model_url_keys k ON c.context_url=k.url WHERE k.error IS NULL
