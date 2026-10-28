SELECT f.document_id AS legacy_document_id,f.source_id AS legacy_source_id,f.body_key,f.source_url,
 coalesce(CASE WHEN trim(f.filename)<>'' THEN f.filename END,n.filename) AS filename,
 CASE WHEN coalesce(CASE WHEN trim(f.filename)<>'' THEN f.filename END,n.filename) IS NULL THEN 'seed_missing_source_filename'
 WHEN d.legacy_document_id IS NULL THEN 'seed_source_outside_documents'
 WHEN d.exclusion_reason IS NOT NULL THEN 'seed_document_excluded' END AS exclusion_reason
FROM seed_file_values f
LEFT JOIN seed_name_url n ON (f.body_key IS NOT DISTINCT FROM n.body_key) AND (f.source_url IS NOT DISTINCT FROM n.source_url)
LEFT JOIN seed_document_admission d ON f.document_id=d.legacy_document_id
