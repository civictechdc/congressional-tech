WITH ranked AS (
 SELECT m.*,row_number() OVER(PARTITION BY m.component ORDER BY coalesce(p.rank,2147483647),
 CASE WHEN p.rank IS NULL THEN m.format ELSE '' END,coalesce(m.exact_bytes,false) DESC,
 m.first_fetched DESC NULLS LAST,m.body_sha,m.source_id) AS saved_rank
 FROM formats p RIGHT JOIN (SELECT * FROM document_members WHERE is_real_file) m
  ON p.kind='preference' AND p.value=m.format
)
SELECT * FROM ranked
