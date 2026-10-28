-- Preserve isolated components and use one edge per review, never a member clique.
WITH keys AS (
 SELECT DISTINCT k.component,k.link_key FROM initial_document_link_keys k
 WHERE NOT EXISTS (SELECT 1 FROM document_link_key_conflicts x WHERE x.link_key=k.link_key)
)
SELECT DISTINCT 'c:'||component AS left_node,'c:'||component AS right_node FROM component_members
UNION SELECT 'c:'||a.component,'c:'||b.component FROM current_reviews r
JOIN keys a ON r.target=a.link_key JOIN keys b ON r.value_text=b.link_key WHERE r.verdict='duplicate_of'
