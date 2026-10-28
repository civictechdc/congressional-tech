SELECT d.legacy_document_id,CASE WHEN filename IS NULL OR trim(filename)='' THEN 'seed_missing_filename'
 WHEN format IS NULL OR trim(format)='' THEN 'seed_missing_format'
 WHEN m.member_count IS NULL THEN 'seed_without_sources' END AS exclusion_reason
FROM seed_docs d LEFT JOIN (SELECT legacy_document_id,count(*) AS member_count
 FROM seed_all_members GROUP BY legacy_document_id) m USING(legacy_document_id)
