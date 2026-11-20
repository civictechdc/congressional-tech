-- Unnested GovInfo MODS citation fields from pinned_readings (ct-n131).
-- Materialized once so package and constituent granule lookups scan only MODS rows, never pinned_readings twice.
SELECT body_sha,f['field'] AS field,nullif(trim(f['value']),'') AS value
FROM (SELECT body_sha,unnest(fields) AS f FROM pinned_readings WHERE parser='gpo_mods' AND status='completed')
WHERE nullif(trim(f['value']),'') IS NOT NULL
