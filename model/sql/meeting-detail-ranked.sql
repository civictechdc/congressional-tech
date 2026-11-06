-- Select each clock and locator from the same retained observation.
SELECT *,row_number() OVER (PARTITION BY congress,chamber,event_id,detail_attempt
   ORDER BY retrieved_at DESC NULLS LAST,receipt_key,receipt_line,capture_index) AS attempt_rank,
  row_number() OVER (PARTITION BY congress,chamber,event_id,state
   ORDER BY retrieved_at DESC NULLS LAST,receipt_key,receipt_line,capture_index) AS state_rank,
  named_struct('source_url',requested_url,'retrieved_at',retrieved_at,
   'receipt_key',receipt_key,'receipt_line',receipt_line,'capture_index',capture_index,
   'body_sha256',body_sha256,'meeting_parser_version',meeting_parser_version,
   'proof_parser_version',proof_parser_version) AS evidence
 FROM meeting_detail_evidence
