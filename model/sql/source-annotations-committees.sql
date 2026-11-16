-- Map source_annotation_codes through committee_codes, excluding hsru00 file-server
-- floor hosting on docs.house.gov/(billsthisweek|floor) and Rules Committee Print
-- (-rcp / bill-to-bill_) legislative text files unless the file carries a Rules
-- Committee Clerk proceeding slug or /meetings/RU/ proceeding URL.
WITH mapped AS (
 SELECT DISTINCT f.source_id,c.system_code,c.chamber
 FROM committee_codes c JOIN source_annotation_codes f ON f.code=c.code
),
excluded_hsru AS (
 SELECT DISTINCT s.source_id
 FROM source_files s
 WHERE NOT regexp_like(coalesce(s.filename,''),'(?i)^(?:HHRG|HMTG|HMKP|CRPT)-[0-9]{3}-RU[0-9]{2}-')
  AND NOT regexp_like(coalesce(s.source_url,''),'(?i)/meetings/RU/')
  AND (
   regexp_like(coalesce(s.source_url,''),'(?i)^https?://(?:web[.]archive[.]org/web/[0-9a-z_*]+/https?://)?docs[.]house[.]gov/(?:billsthisweek|floor)(?:/|$)')
   OR regexp_like(coalesce(s.filename,''),'(?i)^(?:bills|cp)-\s*[0-9]+.*-rcp\s*[0-9]|^bill-to-bill_')
  )
)
SELECT m.source_id,
 array_sort(array_distinct(array_agg(m.system_code))) AS committee_keys,
 array_sort(array_distinct(array_agg(m.chamber))) AS chambers
FROM excluded_hsru e
RIGHT JOIN mapped m ON e.source_id=m.source_id
WHERE NOT (starts_with(m.system_code,'hsru') AND e.source_id IS NOT NULL)
GROUP BY m.source_id
