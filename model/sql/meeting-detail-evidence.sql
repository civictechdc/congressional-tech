-- The selected appearance reader rejects list pages and staging supplies no fallback
-- event_id. This exact version hashes that shared staging code too. Other versions
-- remain unknown until their detail-shape behavior is qualified; no parser bump here.
WITH expanded AS (
 SELECT record_sha_hex,parser_version,unnest(meetings) AS m
 FROM selected_meeting_records WHERE source='congress_gov' AND status='completed'
), events AS (
 SELECT decode(record_sha_hex,'hex') AS sha256,parser_version,
  cast(m['congress'] AS INT) AS congress,
  CASE lower(m['chamber']) WHEN 'nochamber' THEN 'joint' ELSE lower(m['chamber']) END AS chamber,
  try_cast(m['event_id'] AS BIGINT) AS event_id
 FROM expanded
), bound AS (
 SELECT c.congress,c.chamber,coalesce(c.event_id,m.event_id) AS event_id,
  c.receipt_key,c.receipt_line,c.capture_index,c.requested_url,c.retrieved_at,
  c.http_status,c.outcome,encode(c.sha256,'hex') AS body_sha256,
  m.parser_version AS meeting_parser_version,a.parser_version AS proof_parser_version,
  c.event_id IS NOT NULL AS detail_attempt,
  CASE
   WHEN c.complete AND c.outcome IN ('stored','unchanged') AND c.http_status BETWEEN 200 AND 299
    AND c.http_status<>202 AND c.route=c.final_route AND m.event_id IS NOT NULL
    AND c.event_id=a.event_id THEN 'successful'
   -- A normal 304 revalidates earlier bytes; it supplies neither new detail proof nor a failure.
   WHEN c.event_id IS NOT NULL AND (c.outcome IN ('failed','request_failed','retry_later','size_limit')
    OR (c.http_status NOT BETWEEN 200 AND 299 AND c.http_status<>304) OR c.complete=false) THEN 'failed'
   WHEN c.event_id IS NULL AND c.complete AND c.outcome IN ('stored','unchanged')
    AND c.http_status BETWEEN 200 AND 299 AND c.http_status<>202 AND c.route=c.final_route
    AND a.parser_version IS NOT NULL AND a.event_id IS NULL AND a.collection_state='absent'
    AND m.event_id IS NOT NULL THEN 'listing'
   ELSE 'unknown'
  END AS state
 FROM congress_gov_routes c
 LEFT JOIN events m ON c.sha256=m.sha256 AND c.congress=m.congress AND c.chamber=m.chamber
  AND (c.event_id IS NULL OR c.event_id=m.event_id)
 LEFT JOIN selected_appearance_records a ON c.sha256=decode(a.record_sha_hex,'hex')
  AND a.source='congress_gov' AND a.status='completed'
  AND a.parser_version='6d9460f5ec203c24c508846092505a875710f565e1ff026479b542c7555e7d48'
)
SELECT DISTINCT * FROM bound WHERE event_id IS NOT NULL
