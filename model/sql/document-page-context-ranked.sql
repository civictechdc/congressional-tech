SELECT c.*,n.context_count,n.context_bytes,
 row_number() OVER (PARTITION BY c.doc_key ORDER BY c.context_url) AS context_position
FROM document_page_context_counts n JOIN document_page_contexts c ON c.doc_key=n.doc_key
