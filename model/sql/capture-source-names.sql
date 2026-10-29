-- Resolve each capture name and import policy once before the anti-join.
SELECT c.*,f.filename,f.source_url,r.is_real_file,r.record_role,
 encode(c.sha256,'hex') AS body_sha,i.date AS import_date
 FROM import_runs i RIGHT JOIN (
  (effective_filenames f JOIN record_roles r
   ON f.input_id=encode(sha256(json_array(r.receipt_key,r.receipt_line,r.capture_index)),'hex'))
  JOIN capture_evidence c USING(receipt_key,receipt_line,capture_index)
 ) ON c.run_id=i.run_id WHERE c.mode='fetch'
