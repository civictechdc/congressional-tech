SELECT r.*,row_number() OVER(PARTITION BY component ORDER BY
 CASE kind WHEN 'recovered_document' THEN 0 WHEN 'full_recording_recovered' THEN 0
 WHEN 'requested_content_in_official_hearing' THEN 2 ELSE 1 END,
 cast(imported_at AS TIMESTAMP WITH TIME ZONE) DESC NULLS LAST,body_sha,receipt_key,receipt_line,capture_index) AS saved_rank
FROM final_recovery_attachments r
