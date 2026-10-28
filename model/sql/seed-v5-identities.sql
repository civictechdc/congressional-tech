WITH grouped AS (
 SELECT legacy_document_id,
 array_agg(DISTINCT logical_body_key ORDER BY logical_body_key) FILTER(WHERE logical_body_key IS NOT NULL) AS body_keys,
 array_agg(DISTINCT source_id ORDER BY source_id) AS source_ids
 FROM seed_members GROUP BY legacy_document_id
), canonical AS (
 SELECT legacy_document_id,coalesce(body_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS body_keys,source_ids FROM grouped
)
SELECT *,encode(sha256(CASE WHEN cardinality(body_keys)>0 THEN json_array('bodies',body_keys)
 ELSE json_array('sources',source_ids) END),'hex') AS document_id FROM canonical
