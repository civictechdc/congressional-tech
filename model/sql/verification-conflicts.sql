-- Complementary fields may share an instant; contradictory nonnull facts may not.
SELECT key,cast(checked_at AS TIMESTAMP WITH TIME ZONE) AS checked_at,
 (regexp_match(key,'/([0-9a-f]{64})(?:[.]gz|[.]pdf)?$'))[1] AS body_sha
FROM verification_records GROUP BY key,cast(checked_at AS TIMESTAMP WITH TIME ZONE)
HAVING min(size)<>max(size) OR min(intact)<>max(intact)
