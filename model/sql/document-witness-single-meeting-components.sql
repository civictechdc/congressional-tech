SELECT component,try_cast(meeting_keys[1] AS BIGINT) AS event_id
FROM document_metadata
WHERE array_length(meeting_keys)=1 AND try_cast(meeting_keys[1] AS BIGINT) IS NOT NULL
UNION
SELECT r.component,try_cast(a.meeting_keys[1] AS BIGINT) AS event_id
FROM saved_recoveries r
JOIN effective_filenames n ON n.input_id='recovery:'||r.id
JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
JOIN source_annotations a ON f.source_id=a.source_id
WHERE array_length(a.meeting_keys)=1 AND try_cast(a.meeting_keys[1] AS BIGINT) IS NOT NULL
