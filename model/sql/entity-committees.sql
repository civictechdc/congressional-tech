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
), committee_code_map AS (
 SELECT raw_key,min(system_code) AS norm_code,min(chamber) AS map_chamber
 FROM (
  SELECT upper(trim(code)) AS raw_key,lower(trim(system_code)) AS system_code,lower(trim(chamber)) AS chamber FROM committee_codes WHERE code IS NOT NULL AND system_code IS NOT NULL
  UNION ALL
  SELECT 'HS'||upper(trim(code)) AS raw_key,lower(trim(system_code)) AS system_code,lower(trim(chamber)) AS chamber FROM committee_codes WHERE chamber='house' AND length(trim(code))=4 AND system_code IS NOT NULL
  UNION ALL
  SELECT upper(trim(system_code)) AS raw_key,lower(trim(system_code)) AS system_code,lower(trim(chamber)) AS chamber FROM committee_codes WHERE system_code IS NOT NULL
  UNION ALL SELECT 'HSJL00' AS raw_key,'jslc00' AS system_code,'joint' AS chamber
  UNION ALL SELECT 'HSIT00' AS raw_key,'jstx00' AS system_code,'joint' AS chamber
  UNION ALL SELECT 'HSEC00' AS raw_key,'jsec00' AS system_code,'joint' AS chamber
  UNION ALL SELECT 'HSJP00' AS raw_key,'jspr00' AS system_code,'joint' AS chamber
 )
 GROUP BY raw_key
), roster_normalized_committees AS (
 SELECT
  coalesce(ccm.norm_code,lower(trim(a.system_code))) AS norm_code,
  nullif(trim(a.committee_name),'') AS committee_name,
  coalesce(
   CASE lower(trim(a.chamber))
    WHEN 'h' THEN 'house'
    WHEN 's' THEN 'senate'
    WHEN 'j' THEN 'joint'
    ELSE lower(nullif(trim(a.chamber),''))
   END,
   ccm.map_chamber
  ) AS chamber,
  a.is_subcommittee,
  coalesce(pccm.norm_code,lower(nullif(trim(a.parent_system_code),''))) AS parent_system_code
 FROM spicy_committee_assignments a
 LEFT JOIN committee_code_map ccm ON ccm.raw_key=upper(trim(a.system_code))
 LEFT JOIN committee_code_map pccm ON pccm.raw_key=upper(trim(a.parent_system_code))
 WHERE a.system_code IS NOT NULL AND trim(a.system_code)<>''
), synthesized_committees AS (
 SELECT
  r.norm_code,
  coalesce(
   max(r.committee_name),
   upper(r.norm_code)
  ) AS name,
  coalesce(
   max(r.chamber),
   CASE substr(r.norm_code,1,1)
    WHEN 'h' THEN 'house'
    WHEN 's' THEN 'senate'
    WHEN 'j' THEN 'joint'
    ELSE 'house'
   END
  ) AS chamber,
  -- A directory-defined body has no Congress.gov code (upstream entry_label no_congress_gov_code), e.g. the 114th
  -- House Financial Services task force hsba00-tf-terrorism-financing: its type and parent come from the seat.
  CASE
   WHEN r.norm_code LIKE '%-tf-%' THEN 'task force'
   WHEN bool_or(coalesce(r.is_subcommittee,substr(r.norm_code,5,2)<>'00')) THEN 'subcommittee'
   WHEN r.norm_code LIKE 'j%' THEN 'joint'
   ELSE 'standing'
  END AS committee_type,
  CASE
   WHEN substr(r.norm_code,5,2)<>'00' THEN coalesce(max(r.parent_system_code),substr(r.norm_code,1,4)||'00')
   WHEN r.norm_code LIKE '%-tf-%' THEN max(r.parent_system_code)
   ELSE cast(NULL AS VARCHAR)
  END AS parent_system_code,
  cast(NULL AS VARCHAR) AS website,
  false AS is_current
 FROM roster_normalized_committees r
 LEFT ANTI JOIN base_committees b ON b.norm_code=r.norm_code
 GROUP BY r.norm_code
), all_committees AS (
 SELECT * FROM base_committees
 UNION ALL
 SELECT * FROM synthesized_committees
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
FROM all_committees c
LEFT JOIN names_agg n ON c.norm_code=n.agg_system_code
