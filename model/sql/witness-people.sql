-- Assign person_key and grouping_basis to eligible witness rows (ct-ha10).
-- Tier 1: Members by Bioguide ID (matched_bioguide_id or valid publisher bioguide_id).
-- Tier 2: Non-Members by exact normalized name + full normalized organization with middle-initial
-- and suffix guards (min(x)=max(x) joins unstated rows to a single stated value and splits when
-- two stated values compete). Empty organization or unusable name falls back to a singleton key.
-- Superseded rows inherit their canonical witness's person_key; record entries and unmatched
-- member_appearance rows receive NULL (omitted from witness_people).
WITH active_decisions AS (
 SELECT d.witness_key,d.decision_id,d.kind,d.target_key
 FROM person_decisions d
 WHERE d.action='accepted'
  AND NOT EXISTS (SELECT 1 FROM person_decisions r WHERE r.action='revoked' AND r.target_key=d.decision_id)
), shown_eligible AS (
 SELECT *
 FROM witness_person_facts
 WHERE superseded_by IS NULL
  AND name IS NOT NULL
  AND coalesce(eff_witness_type,'') NOT IN ('statement_for_record','member_statement','record_material')
), tier1_members AS (
 SELECT
  witness_key,
  member_bioguide_id AS person_key,
  'bioguide' AS grouping_basis
 FROM shown_eligible
 WHERE member_bioguide_id IS NOT NULL
), tier2_pool AS (
 SELECT
  *,
  (
   name_key IS NOT NULL
   AND org_key NOT IN (
    '','self','none','na','n a','unknown','tbd','witness','witnesses','individual',
    'private citizen','citizen','inc','llc','llp','corp','ltd','pc','plc','pllc',
    'senator','u s senator','united states senator','representative','u s representative','member of congress'
   )
  ) AS is_mergeable
 FROM shown_eligible
 WHERE member_bioguide_id IS NULL
  AND coalesce(eff_witness_type,'')<>'member_appearance'
), tier2_mergeable AS (
 SELECT *
 FROM tier2_pool
 WHERE is_mergeable
), mid_guarded AS (
 SELECT
  m.*,
  CASE
   WHEN min_mid IS NOT NULL AND min_mid=max_mid THEN min_mid
   ELSE m.middle_norm
  END AS eff_mid
 FROM (
  SELECT
   tm.*,
   min(nullif(tm.middle_norm,'')) OVER(PARTITION BY tm.name_key,tm.org_key) AS min_mid,
   max(nullif(tm.middle_norm,'')) OVER(PARTITION BY tm.name_key,tm.org_key) AS max_mid
  FROM tier2_mergeable tm
 ) m
), suf_guarded AS (
 SELECT
  s.witness_key,
  substr(encode(sha256(json_array(
   'person-v1',
   s.name_key,
   s.org_key,
   s.eff_mid,
   CASE
    WHEN s.min_suf IS NOT NULL AND s.min_suf=s.max_suf THEN s.min_suf
    ELSE s.suffix_norm
   END
  )),'hex'),1,16) AS person_key,
  'name_organization' AS grouping_basis
 FROM (
  SELECT
   mg.*,
   min(nullif(mg.suffix_norm,'')) OVER(PARTITION BY mg.name_key,mg.org_key,mg.eff_mid) AS min_suf,
   max(nullif(mg.suffix_norm,'')) OVER(PARTITION BY mg.name_key,mg.org_key,mg.eff_mid) AS max_suf
  FROM mid_guarded mg
 ) s
), tier2_singletons AS (
 SELECT
  witness_key,
  substr(encode(sha256(json_array('person-singleton-v1',witness_key)),'hex'),1,16) AS person_key,
  'singleton' AS grouping_basis
 FROM tier2_pool
 WHERE NOT is_mergeable
), canonical_raw AS (
 SELECT * FROM tier1_members
 UNION ALL
 SELECT * FROM suf_guarded
 UNION ALL
 SELECT * FROM tier2_singletons
), canonical_assigned AS (
 SELECT
  c.witness_key,
  CASE
   WHEN d.kind='hide' THEN NULL
   WHEN d.kind IN ('merge','split') AND nullif(trim(d.target_key),'') IS NOT NULL THEN trim(d.target_key)
   ELSE c.person_key
  END AS person_key,
  CASE
   WHEN d.kind IN ('merge','split') AND nullif(trim(d.target_key),'') IS NOT NULL THEN 'reviewed'
   ELSE c.grouping_basis
  END AS grouping_basis,
  d.decision_id,
  d.kind AS decision_kind
 FROM active_decisions d
 RIGHT JOIN canonical_raw c ON d.witness_key=c.witness_key
), canonical_kept AS (
 SELECT witness_key,person_key,grouping_basis,decision_id,decision_kind
 FROM canonical_assigned
 WHERE person_key IS NOT NULL
), superseded_inherited AS (
 SELECT
  f.witness_key,
  ck.person_key,
  ck.grouping_basis,
  ck.decision_id,
  ck.decision_kind
 FROM witness_person_facts f
 JOIN canonical_kept ck ON ck.witness_key=f.superseded_by
 WHERE f.superseded_by IS NOT NULL
)
SELECT * FROM canonical_kept
UNION ALL
SELECT * FROM superseded_inherited
