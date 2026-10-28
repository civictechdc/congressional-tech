-- Requires materialized url_normalized from url-normalized.sql.
WITH mappings AS (
 SELECT DISTINCT v.base_key AS variant,c.base_key AS canonical,
 v.error AS variant_error,c.error AS canonical_error
 FROM url_variants p JOIN url_normalized v ON p.variant_url IS NOT DISTINCT FROM v.url
 JOIN url_normalized c ON p.canonical_url IS NOT DISTINCT FROM c.url
), validation AS (
 SELECT CASE WHEN count(*)>0 THEN 1 END AS priority FROM (SELECT input_id FROM url_inputs GROUP BY input_id HAVING count(*)>1)
 UNION ALL SELECT CASE WHEN count(*)>0 THEN 2 END FROM (SELECT variant FROM mappings GROUP BY variant HAVING min(canonical)<>max(canonical))
 UNION ALL SELECT CASE WHEN count(*)>0 THEN 3 END FROM mappings a JOIN mappings b ON a.canonical=b.variant
 UNION ALL SELECT CASE WHEN count(*)>0 THEN 4 END FROM mappings WHERE variant_error IS NOT NULL OR canonical_error IS NOT NULL
), checks AS (
 SELECT CASE min(priority) WHEN 1 THEN 'duplicate_input' WHEN 2 THEN 'variant_conflict'
 WHEN 3 THEN 'variant_chain' WHEN 4 THEN 'invalid_variant' END AS error FROM validation
), resolved_mappings AS (
 SELECT variant,max(canonical) AS canonical FROM mappings GROUP BY variant
), selected AS (
 SELECT i.input_id,i.url,coalesce(checks.error,b.error) AS error,
 coalesce(m.canonical,b.base_key) AS candidate,coalesce(b.still_wrapped,false) AS still_wrapped
 FROM url_inputs i CROSS JOIN checks
 LEFT JOIN url_normalized b ON i.url IS NOT DISTINCT FROM b.url
 LEFT JOIN resolved_mappings m ON b.base_key=m.variant
)
SELECT input_id,url,CASE WHEN error IS NULL THEN candidate END AS url_key,error,still_wrapped FROM selected
