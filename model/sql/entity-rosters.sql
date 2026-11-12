WITH committee_code_map AS (
 SELECT raw_key,min(system_code) AS norm_code
 FROM (
  SELECT upper(trim(code)) AS raw_key,lower(trim(system_code)) AS system_code FROM committee_codes WHERE code IS NOT NULL AND system_code IS NOT NULL
  UNION ALL
  SELECT 'HS'||upper(trim(code)) AS raw_key,lower(trim(system_code)) AS system_code FROM committee_codes WHERE chamber='house' AND length(trim(code))=4 AND system_code IS NOT NULL
  UNION ALL
  SELECT upper(trim(system_code)) AS raw_key,lower(trim(system_code)) AS system_code FROM committee_codes WHERE system_code IS NOT NULL
  UNION ALL SELECT 'HSJL00' AS raw_key,'jslc00' AS system_code
  UNION ALL SELECT 'HSIT00' AS raw_key,'jstx00' AS system_code
  UNION ALL SELECT 'HSEC00' AS raw_key,'jsec00' AS system_code
  UNION ALL SELECT 'HSJP00' AS raw_key,'jspr00' AS system_code
 )
 GROUP BY raw_key
), raw_assignments AS (
 SELECT
  cast(a.congress AS SMALLINT) AS congress,
  nullif(trim(a.session),'') AS session,
  coalesce(ccm.norm_code,lower(trim(a.system_code))) AS system_code,
  trim(a.bioguide_id) AS bioguide_id,
  nullif(trim(a.position),'') AS title,
  CASE WHEN nullif(trim(a.position),'') IS NULL THEN 1 ELSE 0 END AS title_missing,
  try_cast(nullif(trim(cast(a.rank AS VARCHAR)),'') AS INT) AS parsed_rank,
  nullif(trim(a.party),'') AS raw_party,
  -- Source labels (ss-ehci, ct-sh1i): which source a seat comes from, its directory edition date or Wayback capture
  -- date, its printed line, whether its position is printed or inferred, and the printed entry when corrected.
  nullif(trim(a.congress_basis),'') AS congress_basis,
  try_cast(nullif(trim(a.edition_date),'') AS DATE) AS stated_edition_date,
  nullif(trim(a.source_granule),'') AS source_granule,
  CASE
   WHEN strpos(coalesce(a.source_granule,''),'/web/') > 0
   THEN substr(trim(a.source_granule),strpos(trim(a.source_granule),'/web/') + 5,8)
   ELSE NULL
  END AS wayback_ymd,
  nullif(trim(a.source_line),'') AS source_line,
  nullif(trim(a.position_basis),'') AS position_basis,
  nullif(trim(a.printed_entry),'') AS printed_entry,
  nullif(trim(a.entry_label),'') AS entry_label
 FROM spicy_committee_assignments a
 LEFT JOIN committee_code_map ccm ON ccm.raw_key=upper(trim(a.system_code))
 WHERE a.congress IS NOT NULL
   AND a.system_code IS NOT NULL AND trim(a.system_code)<>''
   AND a.bioguide_id IS NOT NULL AND trim(a.bioguide_id)<>''
), normalized_assignments AS (
 SELECT
  congress,session,system_code,bioguide_id,title,title_missing,parsed_rank,raw_party,congress_basis,
  coalesce(
   stated_edition_date,
   CASE
    WHEN wayback_ymd IS NOT NULL AND length(wayback_ymd)=8
    THEN try_cast(substr(wayback_ymd,1,4)||'-'||substr(wayback_ymd,5,2)||'-'||substr(wayback_ymd,7,2) AS DATE)
    ELSE NULL
   END
  ) AS edition_date,
  source_granule,source_line,position_basis,printed_entry,entry_label
 FROM raw_assignments
), chamber_file_committees AS (
 -- When a Congress combines archived chamber files with a Congressional Directory reading, each committee covered by
 -- a chamber file uses that snapshot alone rather than merging departed or reassigned Directory seats (ct-sh1i).
 SELECT DISTINCT congress,system_code
 FROM normalized_assignments
 WHERE congress_basis IN ('file','caller')
), single_snapshot_assignments AS (
 SELECT na.*
 FROM chamber_file_committees cfc
 RIGHT JOIN normalized_assignments na
  ON cfc.congress=na.congress AND cfc.system_code=na.system_code
 WHERE NOT (na.congress_basis IN ('directory','directory-manual') AND cfc.system_code IS NOT NULL)
), dedup_assignments AS (
 SELECT *,
  row_number() OVER (
   PARTITION BY congress,system_code,bioguide_id
   ORDER BY session DESC NULLS LAST,title_missing ASC,parsed_rank ASC NULLS LAST,
    congress_basis ASC NULLS LAST,source_granule ASC NULLS LAST,source_line ASC NULLS LAST
  ) AS rn
 FROM single_snapshot_assignments
), selected_assignments AS (
 SELECT
  d.congress,
  d.system_code,
  d.bioguide_id,
  d.title,
  d.parsed_rank,
  -- Service-term party is not dated roster-party evidence.
  d.raw_party AS party,
  d.congress_basis,d.edition_date,d.source_granule,d.source_line,d.position_basis,d.printed_entry,d.entry_label
 FROM dedup_assignments d
 WHERE d.rn=1
), parsed_member_terms AS (
 SELECT
  trim(bioguide_id) AS bioguide_id,
  try_cast(substr(trim(term_start),1,10) AS DATE) AS start_date,
  nullif(trim(term_end),'') AS end_raw,
  try_cast(substr(trim(term_end),1,10) AS DATE) AS end_date
 FROM spicy_member_terms
 WHERE bioguide_id IS NOT NULL
   AND try_cast(substr(trim(term_start),1,10) AS DATE) IS NOT NULL
), dated_member_seats AS (
 SELECT DISTINCT congress,bioguide_id,edition_date
 FROM selected_assignments
 WHERE edition_date IS NOT NULL
), departed_member_seats AS (
 SELECT
  d.congress,
  d.bioguide_id,
  d.edition_date
 FROM dated_member_seats d
 JOIN parsed_member_terms t
  ON t.bioguide_id=d.bioguide_id
  AND t.start_date < try_cast(cast(1789 + (cast(d.congress AS INT) - 1) * 2 + 2 AS VARCHAR)||'-01-03' AS DATE)
 GROUP BY d.congress,d.bioguide_id,d.edition_date
 HAVING count(*) FILTER (WHERE t.start_date <= d.edition_date) > 0
   AND count(*) FILTER (
    WHERE (t.start_date <= d.edition_date AND (t.end_raw IS NULL OR t.end_date IS NULL OR t.end_date >= d.edition_date))
     OR t.start_date > d.edition_date
   ) = 0
)
SELECT
 s.congress,
 s.system_code,
 s.bioguide_id,
 s.title,
 -- Unprinted source ranks stay null rather than inventing sequential numbers (ct-sh1i).
 cast(s.parsed_rank AS SMALLINT) AS rank,
 s.party,
 s.congress_basis,
 s.edition_date,
 s.source_granule,
 s.source_line,
 s.position_basis,
 s.printed_entry,
 CASE
  WHEN s.entry_label IS NOT NULL THEN s.entry_label
  WHEN dep.bioguide_id IS NOT NULL THEN 'after_departure'
  ELSE NULL
 END AS entry_label
FROM departed_member_seats dep
RIGHT JOIN selected_assignments s
 ON dep.congress=s.congress AND dep.bioguide_id=s.bioguide_id AND dep.edition_date=s.edition_date
