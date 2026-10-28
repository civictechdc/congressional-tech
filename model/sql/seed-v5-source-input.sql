SELECT i.document_id AS doc_key,min(m.source_id) AS source_key,m.source_url AS url,
 cast(NULL AS VARCHAR) AS member_path,bool_or(coalesce(m.body_key=d.body_key,false)) AS is_saved,
 cast(NULL AS DATE) AS first_seen,min(m.listed_on) AS listed_on,min(m.link_text) AS link_text,
 min(m.doc_type) AS doc_type,min(m.posted) AS posted
FROM seed_members m JOIN seed_identities i USING(legacy_document_id)
JOIN seed_representatives r ON i.document_id=r.document_id
JOIN seed_docs d ON r.legacy_document_id=d.legacy_document_id
WHERE m.source_url IS NOT NULL
GROUP BY i.document_id,m.source_url
