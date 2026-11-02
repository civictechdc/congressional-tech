-- DM 7.5 recovered_copy (owner, 2026-11-02): a recovered copy (display kind recovered_document or
-- full_recording_recovered) whose body is byte-identical, sha and size, to a real body makes its
-- original link's own source file (DM 7.4) another address of the document holding that body
-- (grouping_steps: recovered_copy_members). One row per (link source file, body); other recovery
-- kinds keep their own documents.
SELECT DISTINCT f.source_id,r.original_url,r.body_sha
FROM model_recovery_rows r
JOIN effective_filenames n ON n.input_id='recovery:'||r.id
JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
JOIN body_evidence b ON b.body_sha=r.body_sha AND b.original_size=r.bytes
WHERE r.kind IN ('recovered_document','full_recording_recovered')
 AND EXISTS (SELECT 1 FROM source_files s WHERE s.body_sha=r.body_sha AND s.is_real_file)
