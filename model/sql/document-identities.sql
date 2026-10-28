SELECT m.component,encode(sha256(CASE WHEN max(cardinality(b.logical_keys))>0
 THEN json_array('bodies',max(b.logical_keys)) ELSE json_array('sources',array_agg(DISTINCT m.source_id ORDER BY m.source_id)) END),'hex') AS document_id,
 bool_or(m.is_real_file) AS has_real
FROM document_members m LEFT JOIN document_bodies b USING(component) GROUP BY m.component
