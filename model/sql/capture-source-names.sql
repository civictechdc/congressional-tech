-- Resolve each capture name and import policy once before the anti-join.
SELECT c.*,f.filename,f.source_url,r.is_real_file,r.record_role,
 encode(c.sha256,'hex') AS body_sha,i.date AS import_date
 FROM capture_evidence c JOIN effective_filenames f
 ON f.input_id=encode(sha256(json_array(c.receipt_key,c.receipt_line,c.capture_index)),'hex')
 JOIN record_roles r USING(receipt_key,receipt_line,capture_index)
 LEFT JOIN import_runs i ON c.run_id=i.run_id WHERE c.mode='fetch'
