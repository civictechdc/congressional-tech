-- Normalize each distinct literal once; invalid mentions remain unresolved.
SELECT DISTINCT encode(sha256(json_array(source_url)),'hex') AS input_id,source_url AS url
FROM capture_source_names WHERE source_url IS NOT NULL
