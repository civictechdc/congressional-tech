-- Summarize only the small, bound evidence relation.
WITH counts AS (
 SELECT congress,chamber,event_id,
  bool_or(state='successful') AS successful,
  bool_or(detail_attempt AND state='unknown') AS uncertain,
  bool_or(state='failed') AS failed,
  bool_or(state='listing') AS listed,
  bool_or(detail_attempt AND retrieved_at IS NULL) AS has_undated_attempt
 FROM meeting_detail_evidence GROUP BY congress,chamber,event_id
)
SELECT c.congress,c.chamber,c.event_id,
 CASE WHEN c.successful THEN 'successful' WHEN c.uncertain THEN 'unknown'
      WHEN c.failed THEN 'failed' WHEN c.listed THEN 'listing_only_in_scope' ELSE 'unknown' END AS state,
 'selected_release_inputs' AS coverage,
 CASE WHEN s.receipt_key IS NOT NULL THEN s.evidence END AS successful_read,
 CASE WHEN a.receipt_key IS NOT NULL THEN named_struct('evidence',a.evidence,
  'state',a.state,'outcome',a.outcome,'http_status',a.http_status) END AS latest_attempt,
 CASE WHEN l.receipt_key IS NOT NULL THEN l.evidence END AS listing,
 c.has_undated_attempt
FROM counts c
LEFT JOIN meeting_detail_ranked s ON c.congress=s.congress AND c.chamber=s.chamber AND c.event_id=s.event_id
 AND s.state='successful' AND s.state_rank=1
LEFT JOIN meeting_detail_ranked a ON c.congress=a.congress AND c.chamber=a.chamber AND c.event_id=a.event_id
 AND a.detail_attempt AND a.attempt_rank=1
LEFT JOIN meeting_detail_ranked l ON c.congress=l.congress AND c.chamber=l.chamber AND c.event_id=l.event_id
 AND l.state='listing' AND l.state_rank=1
