-- Unnested GovInfo MODS citation fields from selected_readings (ct-n131).
-- Reads selected_readings directly (never pinned_readings, which releases after page_facts)
-- and materializes once so package and constituent granule lookups scan only MODS rows.
SELECT body_sha,f['field'] AS field,nullif(trim(f['value']),'') AS value
FROM (SELECT body_sha,unnest(fields) AS f FROM selected_readings WHERE parser='gpo_mods' AND status='completed')
WHERE nullif(trim(f['value']),'') IS NOT NULL
