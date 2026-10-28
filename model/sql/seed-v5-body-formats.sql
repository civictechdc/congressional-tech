WITH byte_formats AS (SELECT body_key,lower(unnest(response_format)) AS format FROM seed_file_values WHERE body_key IS NOT NULL)
SELECT body_key,min(format) AS format,count(DISTINCT format) AS candidates
FROM byte_formats WHERE format IS NOT NULL AND trim(format)<>'' GROUP BY body_key
