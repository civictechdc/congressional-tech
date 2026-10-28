-- Phase one has line outcomes and deterministic family bands, never Retry-After.
WITH history AS (
 SELECT l.requested_url,cast(count(*) AS INT) AS attempts,
 max(CASE WHEN g.receipt_key IS NOT NULL THEN l.retrieved_at END) AS last_good_at
 FROM url_state_lines l LEFT JOIN url_state_good_lines g USING(receipt_key,receipt_line)
 WHERE l.requested_url IS NOT NULL GROUP BY l.requested_url
)
SELECT h.requested_url,h.attempts,l.retrieved_at AS last_attempt,
 cast(l.http_status AS SMALLINT) AS last_status,l.outcome AS last_outcome,h.last_good_at,
 arrow_cast(to_timestamp_micros(arrow_cast(l.retrieved_at,'Int64')+i.interval_seconds*1000000),'Timestamp(Microsecond, Some("UTC"))') AS next_attempt_at
FROM history h JOIN url_state_latest l ON h.requested_url=l.requested_url
LEFT JOIN url_state_intervals i ON l.requested_url=i.requested_url
UNION ALL
SELECT requested_url,cast(0 AS INT) AS attempts,{{TS}} AS last_attempt,
 cast(NULL AS SMALLINT) AS last_status,cast(NULL AS VARCHAR) AS last_outcome,
 {{TS}} AS last_good_at,{{TS}} AS next_attempt_at FROM url_state_queue
