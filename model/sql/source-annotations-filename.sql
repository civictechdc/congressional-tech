-- Filename producers own typed keys; the model joins their exact admitted pair.
SELECT s.source_id,f.* FROM source_files s JOIN filename_readings f
 ON s.filename=f.filename AND (coalesce(s.source_url,'')=f.source_url OR regexp_replace(coalesce(s.source_url,''),'^https?://','')=regexp_replace(f.source_url,'^https?://',''))
WHERE f.catalog_version={{CATALOG_VERSION}}
