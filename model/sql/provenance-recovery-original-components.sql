SELECT DISTINCT r.recovery_id,l.component FROM model_recovery_rows r
JOIN effective_filenames n ON n.input_id='recovery:'||r.id
JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
JOIN source_labels l ON f.source_id=l.source_id
