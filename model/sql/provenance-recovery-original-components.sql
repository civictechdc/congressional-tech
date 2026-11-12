-- When recovered_copy_members moved the bodiless original link into the unique document
-- holding its shown recovered copy (DM 7.5), its component in source_labels contains a real file.
WITH real_components AS (
 SELECT DISTINCT l.component AS real_component
 FROM source_files f JOIN source_labels l ON f.source_id=l.source_id
 WHERE f.is_real_file
), orig AS (
 SELECT DISTINCT r.recovery_id,l.component
 FROM model_recovery_rows r
 JOIN effective_filenames n ON n.input_id='recovery:'||r.id
 JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
 JOIN source_labels l ON f.source_id=l.source_id
)
SELECT orig.recovery_id,orig.component,rc.real_component IS NOT NULL AS is_recovered_copy
FROM orig LEFT JOIN real_components rc ON rc.real_component=orig.component
