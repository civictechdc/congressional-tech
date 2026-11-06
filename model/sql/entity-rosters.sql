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
  nullif(trim(a.name_first),'') AS name_first
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
), distinct_roster_congresses AS (
 SELECT DISTINCT congress FROM dedup_assignments WHERE rn=1
), member_term_parsed AS (
 SELECT
  trim(bioguide_id) AS m_bioguide_id,
  nullif(trim(term_party),'') AS term_party,
  try_cast(substr(trim(term_start),1,10) AS DATE) AS start_date,
  try_cast(substr(trim(term_end),1,10) AS DATE) AS end_date,
  nullif(trim(term_end),'') IS NULL AS end_missing
 FROM spicy_member_terms
 WHERE bioguide_id IS NOT NULL AND nullif(trim(term_party),'') IS NOT NULL
), member_congress_candidates AS (
 SELECT
  c.congress AS m_congress,
  t.m_bioguide_id,
  t.term_party
 FROM distinct_roster_congresses c
 JOIN member_term_parsed t
  ON t.start_date < make_date(1789 + (cast(c.congress AS INT) - 1) * 2 + 2,1,3)
  AND (t.end_missing OR (
   t.end_date > t.start_date
   AND t.end_date > make_date(1789 + (cast(c.congress AS INT) - 1) * 2,1,3)
  ))
), member_parties AS (
 -- Without a roster observation date, conflicting parties cannot be resolved.
 SELECT m_congress,m_bioguide_id,min(term_party) AS term_party
 FROM member_congress_candidates
 GROUP BY m_congress,m_bioguide_id
 HAVING min(term_party)=max(term_party)
), with_party AS (
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
  coalesce(d.raw_party,mp.term_party) AS party
 FROM dedup_assignments d
 LEFT JOIN member_parties mp ON mp.m_congress=d.congress AND mp.m_bioguide_id=d.bioguide_id
 WHERE d.rn=1
), ranked_rosters AS (
 SELECT
  congress,
  system_code,
  bioguide_id,
  title,
  party,
  parsed_rank,
  coalesce(max(parsed_rank) OVER (PARTITION BY congress,system_code,party),0) AS max_explicit_rank,
  row_number() OVER (
   PARTITION BY congress,system_code,party,rank_missing
   ORDER BY title_missing ASC,name_last ASC NULLS LAST,name_first ASC NULLS LAST,bioguide_id ASC
  ) AS missing_rank_seq
 FROM with_party
)
SELECT
 congress,
 system_code,
 bioguide_id,
 title,
 cast(coalesce(parsed_rank,max_explicit_rank + missing_rank_seq) AS SMALLINT) AS rank,
 party
FROM ranked_rosters
