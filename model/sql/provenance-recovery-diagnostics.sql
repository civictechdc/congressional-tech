SELECT receipt_key,receipt_line,capture_index,recovery_id,decision_id,'unknown_recovery_kind' AS error,true AS is_fatal
FROM model_recovery_rows r WHERE kind IS NULL OR NOT EXISTS (SELECT 1 FROM recovery_kinds k WHERE k.kind=r.kind)
UNION ALL SELECT receipt_key,receipt_line,capture_index,recovery_id,decision_id,'missing_original_url',true
FROM model_recovery_rows WHERE original_url IS NULL OR trim(original_url)=''
UNION ALL SELECT receipt_key,receipt_line,capture_index,recovery_id,decision_id,'missing_recovery_body',true
FROM model_recovery_rows WHERE body_sha IS NULL
UNION ALL SELECT cast(NULL AS VARCHAR) AS receipt_key,cast(NULL AS INT) AS receipt_line,cast(NULL AS INT) AS capture_index,cast(NULL AS VARCHAR) AS recovery_id,d.id AS decision_id,'unmatched_recovery_decision' AS error,false AS is_fatal
FROM remaining_recovery_decisions d WHERE NOT EXISTS (SELECT 1 FROM recovery_candidates r WHERE r.decision_id=d.id)
