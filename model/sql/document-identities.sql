-- A component's identity is its body keys, else its sorted distinct source IDs. Only
-- components with several members need the ordered aggregate (the per-group list
-- accumulators cost 4.2 GB over 1.83M groups); a single member's list is that member.
-- document_bodies has one row per component (it groups by component), so it joins 1:1.
WITH sizes AS (
 SELECT component,count(*) AS members,min(source_id) AS only_source,bool_or(is_real_file) AS has_real
 FROM document_members GROUP BY component
), several AS (
 SELECT m.component,array_agg(DISTINCT m.source_id ORDER BY m.source_id) AS source_ids
 FROM document_members m JOIN sizes s ON s.component=m.component AND s.members>1
 GROUP BY m.component
)
SELECT s.component,encode(sha256(CASE WHEN cardinality(b.logical_keys)>0
 THEN json_array('bodies',b.logical_keys)
 ELSE json_array('sources',coalesce(x.source_ids,make_array(s.only_source))) END),'hex') AS document_id,
 s.has_real
FROM sizes s LEFT JOIN several x USING(component) LEFT JOIN document_bodies b USING(component)
