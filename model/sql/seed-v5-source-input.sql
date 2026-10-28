WITH targets AS (
 SELECT r.document_id,d.body_key AS saved_body_key
 FROM seed_representatives r JOIN seed_docs d USING(legacy_document_id)
), owners AS (
 SELECT i.legacy_document_id,t.document_id,t.saved_body_key
 FROM targets t JOIN seed_identities i USING(document_id)
)
SELECT i.document_id AS doc_key,min(m.source_id) AS source_key,m.source_url AS url,
 cast(NULL AS VARCHAR) AS member_path,bool_or(coalesce(m.body_key=i.saved_body_key,false)) AS is_saved,
 cast(NULL AS DATE) AS first_seen,min(m.listed_on) AS listed_on,min(m.link_text) AS link_text,
 min(m.doc_type) AS doc_type,min(m.posted) AS posted
FROM owners i JOIN seed_members m USING(legacy_document_id)
WHERE m.source_url IS NOT NULL
GROUP BY i.document_id,m.source_url
