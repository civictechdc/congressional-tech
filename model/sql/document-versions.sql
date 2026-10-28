SELECT m.component,array_agg(DISTINCT v.version_key ORDER BY v.version_key) AS version_keys
FROM document_members m JOIN document_version_keys v USING(source_id) GROUP BY m.component
