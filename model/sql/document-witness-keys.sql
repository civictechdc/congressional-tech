WITH witness_doc_urls AS (
 SELECT witness_key,unnest(document_urls) AS doc_url
 FROM appearance_records_resolved
 WHERE source<>'mods' AND document_urls IS NOT NULL
), witness_url_keys AS (
 SELECT DISTINCT w.witness_key,k.url_key
 FROM witness_doc_urls w
 JOIN appearance_url_keys k ON w.doc_url=k.url
 WHERE k.error IS NULL AND k.url_key IS NOT NULL
), chrg_components AS (
 SELECT DISTINCT component FROM document_packages WHERE regexp_like(package_id,'(?i)^CHRG-')
 UNION
 SELECT DISTINCT m.component FROM document_members m JOIN source_annotations a USING(source_id)
 WHERE regexp_like(a.package_id,'(?i)^CHRG-')
), matched_members AS (
 SELECT m.component,w.witness_key
 FROM document_members m
 JOIN copy_url_keys ck ON m.source_id=ck.source_id
 JOIN witness_url_keys w ON ck.url_key=w.url_key
 WHERE NOT EXISTS (SELECT 1 FROM chrg_components c WHERE c.component=m.component)
 UNION
 SELECT r.component,w.witness_key
 FROM saved_recoveries r
 JOIN recovery_original_keys rk ON r.id=rk.recovery_id
 JOIN witness_url_keys w ON rk.url_key=w.url_key
 WHERE NOT EXISTS (SELECT 1 FROM chrg_components c WHERE c.component=r.component)
)
SELECT component,array_sort(array_distinct(array_agg(witness_key))) AS witness_keys
FROM matched_members GROUP BY component
