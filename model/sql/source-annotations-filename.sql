-- Filename producers own typed keys; the model joins their exact admitted pair.
SELECT s.source_id,f.* FROM source_files s JOIN filename_readings f
 ON s.filename=f.filename AND coalesce(s.source_url,'')=f.source_url
WHERE f.catalog_version={{CATALOG_VERSION}}
