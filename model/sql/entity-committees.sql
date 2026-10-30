WITH history_rows AS (
 SELECT system_code AS raw_system_code,unnest(history) AS h
 FROM spicy_committees WHERE system_code IS NOT NULL AND history IS NOT NULL
), history_parsed AS (
 SELECT lower(raw_system_code) AS system_code,
  nullif(trim(h['officialName']),'') AS name,
  coalesce(
   try_cast(h['startDate'] AS DATE),
   cast(arrow_cast(try_cast(h['startDate'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)
  ) AS start_date,
  coalesce(
   try_cast(h['endDate'] AS DATE),
   cast(arrow_cast(try_cast(h['endDate'] AS TIMESTAMP WITH TIME ZONE) + INTERVAL '1 second','Timestamp(Second, Some("America/New_York"))') AS DATE)
  ) AS end_date
 FROM history_rows WHERE nullif(trim(h['officialName']),'') IS NOT NULL
), names_agg AS (
 SELECT system_code AS agg_system_code,array_agg(named_struct(
  'name',name,'start',start_date,'end',end_date
 ) ORDER BY start_date DESC NULLS LAST,name ASC,end_date DESC NULLS LAST) AS names
 FROM history_parsed GROUP BY system_code
), base_committees AS (
 SELECT lower(system_code) AS norm_code,name,lower(chamber) AS chamber,
  lower(nullif(trim(committee_type),'')) AS committee_type,
  lower(nullif(trim(parent_system_code),'')) AS parent_system_code,
  nullif(trim(website_url),'') AS website,
  coalesce(is_current,false) AS is_current
 FROM spicy_committees WHERE system_code IS NOT NULL
)
SELECT c.norm_code AS system_code,
 c.name,
 c.chamber,
 c.committee_type,
 c.parent_system_code,
 coalesce(n.names,array_slice(make_array(named_struct(
  'name',cast(NULL AS VARCHAR),'start',cast(NULL AS DATE),'end',cast(NULL AS DATE)
 )),1,0)) AS names,
 c.website,
 c.is_current
FROM base_committees c
LEFT JOIN names_agg n ON c.norm_code=n.agg_system_code
