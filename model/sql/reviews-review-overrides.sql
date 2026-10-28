SELECT d.component,coalesce(h.hide_value,false) AS hidden,h.note,
 cast(cast(h.decided_at AS TIMESTAMP WITH TIME ZONE) AS DATE) AS decided_at,
 t.value_text AS title_override,k.kind_override
FROM document_identities d
LEFT JOIN review_selected h ON d.component=h.component AND h.verdict='hide'
LEFT JOIN review_selected t ON d.component=t.component AND t.verdict='title_override'
LEFT JOIN review_kind_overrides k ON d.component=k.component
