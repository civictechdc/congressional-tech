WITH base AS (
 SELECT document_id AS legacy_document_id,filename,source_url,body_key,
 array_element(regexp_match(body_key,'([a-f0-9]{64})'),1) AS body_hex,
 array_element(source_page_url,1) AS listed_on,array_element(source_link_label,1) AS link_text,
 array_element(source_document_type,1) AS doc_type,
 try_cast(array_element(source_document_added_at,1) AS DATE) AS posted,
 lower(coalesce(array_element(format,1),array_element(body_format,1))) AS format,
 array_element(media_type,1) AS media_type
 FROM v5_filenames
), logical AS (
 SELECT *,CASE WHEN body_hex IS NOT NULL THEN 'bodies/sha256/'||substr(body_hex,1,2)||'/'||body_hex||'.gz' END AS logical_body_key
 FROM base
)
SELECT *,encode(sha256(json_array(logical_body_key,filename,source_url)),'hex') AS source_id FROM logical
