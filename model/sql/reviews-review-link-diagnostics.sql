SELECT r.id,'unresolved_review_target' AS error FROM current_reviews r
WHERE NOT EXISTS (SELECT 1 FROM initial_document_link_keys k WHERE k.link_key=r.target)
UNION SELECT r.id,'unresolved_review_value' AS error FROM current_reviews r WHERE r.verdict='duplicate_of'
AND NOT EXISTS (SELECT 1 FROM initial_document_link_keys k WHERE k.link_key=r.value_text)
