-- Publisher memberships precede edition exclusion; fallback never uses one of
-- their source files, even when the publisher group is later rejected.
WITH publisher AS (
 SELECT DISTINCT 'publisher' AS group_kind,
 encode(sha256(json_array(p.page_body,p.context,p.group_path)),'hex') AS group_id,
 f.source_id AS source_id,f.body_sha AS body_sha,f.format AS format
 FROM publisher_links p JOIN source_files f USING(source_id)
 WHERE f.is_real_file AND p.group_path IS NOT NULL
), fallback AS (
 SELECT DISTINCT 'same_stem' AS group_kind,
 encode(sha256(json_array(d.directory_key,d.stem)),'hex') AS group_id,
 f.source_id AS source_id,f.body_sha AS body_sha,f.format AS format
 FROM source_files f JOIN source_directories d ON f.source_id=d.source_id JOIN formats r ON r.kind='preference' AND r.value=f.format
 WHERE f.is_real_file AND d.directory_key IS NOT NULL AND d.stem<>''
 AND NOT EXISTS(SELECT 1 FROM formats x WHERE x.kind='generic_stem' AND x.value=d.stem)
 AND NOT EXISTS(SELECT 1 FROM publisher p WHERE p.source_id=f.source_id)
)
SELECT * FROM publisher UNION ALL SELECT * FROM fallback
