-- One naming input per effective decision/original, including undecided legacy rows.
SELECT DISTINCT id,original_url,recovered_filename,kind,body_sha,decision_id FROM model_recovery_rows
