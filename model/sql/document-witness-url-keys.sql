WITH witness_doc_urls AS (
 SELECT witness_key,unnest(document_urls) AS doc_url
 FROM appearance_records_resolved
 WHERE source<>'mods' AND document_urls IS NOT NULL
)
SELECT DISTINCT w.witness_key,k.url_key
FROM witness_doc_urls w
JOIN appearance_url_keys k ON w.doc_url=k.url
WHERE k.error IS NULL AND k.url_key IS NOT NULL
