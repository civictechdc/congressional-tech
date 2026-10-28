SELECT f.legacy_document_id,f.legacy_source_id,f.body_key,f.source_url,f.filename,
 f.seed_source_filename_from_document,
 CASE WHEN f.filename IS NULL OR trim(f.filename)='' THEN 'seed_missing_source_filename'
 WHEN d.legacy_document_id IS NULL THEN 'seed_source_outside_documents'
 WHEN d.exclusion_reason IS NOT NULL THEN 'seed_document_excluded' END AS exclusion_reason
FROM seed_document_admission d RIGHT JOIN seed_all_members f ON f.legacy_document_id=d.legacy_document_id
