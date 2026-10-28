-- Timestamp comparison is by instant, then ID; a merged document inherits every key.
WITH applicable AS (
 SELECT DISTINCT k.component,r.id,r.verdict,r.value_json,r.value_text,r.note,r.decided_at
 FROM current_reviews r JOIN document_link_keys k ON r.target=k.link_key
 WHERE r.verdict IN ('hide','title_override','kind_override')
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY component,verdict
 ORDER BY cast(decided_at AS TIMESTAMP WITH TIME ZONE) DESC,id DESC) AS selected FROM applicable
)
SELECT *,CASE WHEN verdict='hide' THEN json_get_bool(value_json) END AS hide_value,
 CASE WHEN verdict='kind_override' THEN json_get_array(value_json) END AS kind_values
FROM ranked WHERE selected=1
