SELECT body_key,min(bytes) AS bytes,max(bytes) AS max_bytes,
 min(stored_bytes) AS stored_bytes,max(stored_bytes) AS max_stored_bytes,
 count(*) FILTER(WHERE bytes IS NULL) AS null_bytes
FROM capture_index WHERE body_key IS NOT NULL GROUP BY body_key
