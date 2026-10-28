-- One public key must resolve to one initial document before any duplicate review.
SELECT link_key FROM initial_document_link_keys GROUP BY link_key HAVING count(DISTINCT component)>1
