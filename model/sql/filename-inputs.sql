SELECT encode(sha256(json_array(receipt_key,receipt_line,capture_index)),'hex') AS input_id,
 CASE WHEN member_path IS NULL THEN url END AS source_url,
 requested_url,member_path,h_content_disposition,cast(NULL AS VARCHAR) AS recovered_filename,
 false AS recovery_rejected,CASE WHEN member_path IS NULL THEN context_url END AS context_url FROM filename_captures WHERE mode='fetch' OR (mode='retained_import' AND member_path IS NOT NULL)
UNION ALL SELECT 'recovery:'||id AS input_id,original_url AS source_url,
 original_url AS requested_url,cast(NULL AS VARCHAR) AS member_path,
 cast(NULL AS VARCHAR) AS h_content_disposition,recovered_filename,
 kind='rejected' AS recovery_rejected,cast(NULL AS VARCHAR) AS context_url FROM current_recoveries
