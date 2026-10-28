WITH selected AS (
 SELECT *,row_number() OVER(PARTITION BY key ORDER BY cast(checked_at AS TIMESTAMP WITH TIME ZONE) DESC,key) AS position
 FROM verification_records WHERE sha256_verified
 AND regexp_like(key,'^bodies/sha256/[0-9a-f]{2}/[0-9a-f]{64}[.]pdf$')
)
SELECT (regexp_match(key,'/([0-9a-f]{64})[.]pdf$'))[1] AS body_sha,size,intact
FROM selected WHERE position=1
