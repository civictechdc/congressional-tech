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
), normalized_assignments AS (
 SELECT
  cast(a.congress AS SMALLINT) AS congress,
  nullif(trim(a.session),'') AS session,
  coalesce(ccm.norm_code,lower(trim(a.system_code))) AS system_code,
  trim(a.bioguide_id) AS bioguide_id,
  nullif(trim(a.position),'') AS title,
  CASE WHEN nullif(trim(a.position),'') IS NULL THEN 1 ELSE 0 END AS title_missing,
  try_cast(nullif(trim(cast(a.rank AS VARCHAR)),'') AS INT) AS parsed_rank,
  nullif(trim(a.party),'') AS raw_party,
  nullif(trim(a.name_last),'') AS name_last,
  nullif(trim(a.name_first),'') AS name_first,
  -- Source labels (ss-ehci): which source a seat comes from, its directory edition date and printed line, whether
  -- its position is printed or inferred, and the printed entry when a value was corrected. Empty on chamber files.
  nullif(trim(a.congress_basis),'') AS congress_basis,
  try_cast(nullif(trim(a.edition_date),'') AS DATE) AS edition_date,
  nullif(trim(a.source_granule),'') AS source_granule,
  nullif(trim(a.source_line),'') AS source_line,
  nullif(trim(a.position_basis),'') AS position_basis,
  nullif(trim(a.printed_entry),'') AS printed_entry,
  nullif(trim(a.entry_label),'') AS entry_label
 FROM spicy_committee_assignments a
 LEFT JOIN committee_code_map ccm ON ccm.raw_key=upper(trim(a.system_code))
 WHERE a.congress IS NOT NULL
   AND a.system_code IS NOT NULL AND trim(a.system_code)<>''
   AND a.bioguide_id IS NOT NULL AND trim(a.bioguide_id)<>''
), dedup_assignments AS (
 SELECT *,
  row_number() OVER (
   PARTITION BY congress,system_code,bioguide_id
   ORDER BY session DESC NULLS LAST,title_missing ASC,parsed_rank ASC NULLS LAST
  ) AS rn
 FROM normalized_assignments
), selected_assignments AS (
 SELECT
  d.congress,
  d.system_code,
  d.bioguide_id,
  d.title,
  d.title_missing,
  d.parsed_rank,
  CASE WHEN d.parsed_rank IS NULL THEN 1 ELSE 0 END AS rank_missing,
  d.name_last,
  d.name_first,
  -- Service-term party is not dated roster-party evidence.
  d.raw_party AS party,
  d.congress_basis,d.edition_date,d.source_granule,d.source_line,d.position_basis,d.printed_entry,d.entry_label
 FROM dedup_assignments d
 WHERE d.rn=1
), ranked_rosters AS (
 SELECT
  congress,
  system_code,
  bioguide_id,
  title,
  party,
  congress_basis,edition_date,source_granule,source_line,position_basis,printed_entry,entry_label,
  parsed_rank,
  coalesce(max(parsed_rank) OVER (PARTITION BY congress,system_code,party),0) AS max_explicit_rank,
  row_number() OVER (
   PARTITION BY congress,system_code,party,rank_missing
   ORDER BY title_missing ASC,name_last ASC NULLS LAST,name_first ASC NULLS LAST,bioguide_id ASC
  ) AS missing_rank_seq
 FROM selected_assignments
)
SELECT
 congress,
 system_code,
 bioguide_id,
 title,
 cast(coalesce(parsed_rank,max_explicit_rank + missing_rank_seq) AS SMALLINT) AS rank,
 party,
 congress_basis,
 edition_date,
 source_granule,
 source_line,
 position_basis,
 printed_entry,
 entry_label
FROM ranked_rosters
