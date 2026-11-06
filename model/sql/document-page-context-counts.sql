-- Narrow totals are materialized before joining them back to the address rows.
SELECT doc_key,count(*) AS context_count,sum(octet_length(context_url)) AS context_bytes
FROM document_page_contexts GROUP BY doc_key
