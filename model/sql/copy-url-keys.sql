SELECT DISTINCT a.source_id,k.url_key FROM source_addresses a JOIN model_url_keys k ON a.url=k.url
WHERE k.error IS NULL
