SELECT r.recovery_key,count(DISTINCT i.document_id) AS targets,min(i.document_id) AS doc_key,
 count(DISTINCT CASE WHEN m.body_key IS NULL THEN i.document_id END) AS original_targets,
 min(CASE WHEN m.body_key IS NULL THEN i.document_id END) AS original_doc_key
FROM seed_recovery_candidates r JOIN seed_members m ON r.original_url=m.source_url
JOIN seed_identities i USING(legacy_document_id) GROUP BY r.recovery_key
