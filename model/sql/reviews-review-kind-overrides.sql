SELECT component,array_agg(DISTINCT kind ORDER BY kind) AS kind_override
FROM review_kind_items WHERE kind IS NOT NULL AND kind<>'' GROUP BY component
