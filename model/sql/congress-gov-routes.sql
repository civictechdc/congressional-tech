-- Read the retained capture scope once. No body bytes or digest-wide clock is used.
WITH addressed AS (
 SELECT receipt_key,receipt_line,capture_index,sha256,retrieved_at,http_status,outcome,complete,
  requested_url,url,split_part(requested_url,'?',1) AS route,
  split_part(url,'?',1) AS final_route
 FROM captures
 WHERE mode='fetch' AND receipt_key IS NOT NULL AND receipt_line IS NOT NULL
  AND regexp_like(requested_url,'^https://api[.]congress[.]gov/v3/committee-meeting/[1-9][0-9]*/(house|senate|nochamber)(/[1-9][0-9]*)?([?][^#]*)?$')
)
SELECT *,try_cast(split_part(route,'/',6) AS INT) AS congress,
 CASE split_part(route,'/',7) WHEN 'nochamber' THEN 'joint' ELSE split_part(route,'/',7) END AS chamber,
 try_cast(nullif(split_part(route,'/',8),'') AS BIGINT) AS event_id
FROM addressed
