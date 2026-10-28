WITH base AS (
 SELECT f.document_id AS legacy_document_id,f.source_id AS legacy_source_id,
 coalesce(CASE WHEN trim(f.filename)<>'' THEN f.filename END,n.filename,d.filename) AS filename,f.source_url,f.body_key,
 (coalesce(CASE WHEN trim(f.filename)<>'' THEN f.filename END,n.filename) IS NULL AND d.filename IS NOT NULL) AS seed_source_filename_from_document,
 array_element(regexp_match(f.body_key,'([a-f0-9]{64})'),1) AS body_hex,
 array_element(source_page_url,1) AS listed_on,array_element(source_link_label,1) AS link_text,
 array_element(source_document_type,1) AS doc_type,
 try_cast(array_element(source_document_added_at,1) AS DATE) AS posted,
 lower(coalesce(array_element(format,1),array_element(body_format,1))) AS format,
 array_element(media_type,1) AS media_type
 FROM (SELECT legacy_document_id,body_key,filename FROM seed_docs WHERE body_key IS NOT NULL) d RIGHT JOIN (
 seed_name_url n RIGHT JOIN seed_file_values f
 ON (f.body_key IS NOT DISTINCT FROM n.body_key) AND (f.source_url IS NOT DISTINCT FROM n.source_url)
) ON d.legacy_document_id=f.document_id AND d.body_key=f.body_key
), logical AS (
 SELECT *,CASE WHEN body_hex IS NOT NULL THEN 'bodies/sha256/'||substr(body_hex,1,2)||'/'||body_hex||'.gz' END AS logical_body_key
 FROM base
)
SELECT *,encode(sha256(json_array(logical_body_key,filename,source_url)),'hex') AS source_id FROM logical
