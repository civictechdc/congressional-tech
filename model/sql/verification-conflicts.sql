-- Complementary fields may share a timestamp; contradictory nonnull facts may not.
SELECT key,checked_at,(regexp_match(key,'/([0-9a-f]{64})(?:[.]gz|[.]pdf)?$'))[1] AS body_sha
FROM verification_records GROUP BY key,checked_at
HAVING count(DISTINCT size)>1 OR count(DISTINCT intact)>1
