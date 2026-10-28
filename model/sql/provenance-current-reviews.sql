SELECT r.*,json_get_str(value_json) AS value_text FROM review_records r
WHERE verdict<>'withdraw' AND NOT EXISTS (SELECT 1 FROM review_records s WHERE s.supersedes=r.id)
