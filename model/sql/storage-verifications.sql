-- Size observations require no full hash pass. Key identity was admitted as provenance.
WITH selected AS (
 SELECT *,row_number() OVER(PARTITION BY key ORDER BY cast(checked_at AS TIMESTAMP WITH TIME ZONE) DESC,key) AS position
 FROM verification_records WHERE size IS NOT NULL
 AND regexp_like(key,'^bodies/sha256/[0-9a-f]{2}/[0-9a-f]{64}(?:[.]gz|[.]pdf)?$')
)
SELECT key,size FROM selected WHERE position=1
