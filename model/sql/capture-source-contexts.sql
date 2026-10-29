SELECT source_id,receipt_key,receipt_line,capture_index,body_sha,filename,source_url,requested_url,context_url,member_path,outcome,
 cast(NULL AS VARCHAR) AS fidelity,cast(NULL AS VARCHAR) AS media_type
FROM capture_sources
