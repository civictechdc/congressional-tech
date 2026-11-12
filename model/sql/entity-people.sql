-- Published people table aggregated over canonical (superseded_by IS NULL) witness rows (ct-ha10, P0-3b).
WITH shown AS (
 SELECT
  wp.person_key,
  wp.grouping_basis,
  f.witness_key,
  f.occasion,
  trim(f.name) AS name_clean,
  nullif(trim(f.rank),'') AS rank_clean,
  nullif(trim(f.credentials),'') AS cred_clean,
  nullif(trim(f.organization),'') AS org_clean,
  nullif(trim(f.position),'') AS pos_clean,
  f.hearing_date,
  f.source_priority
 FROM witness_people wp
 JOIN witness_person_facts f ON f.witness_key=wp.witness_key
 WHERE f.superseded_by IS NULL
), base_agg AS (
 SELECT
  person_key,
  (array_agg(name_clean ORDER BY hearing_date DESC NULLS LAST,source_priority ASC,witness_key ASC))[1] AS name,
  (array_agg(rank_clean ORDER BY hearing_date DESC NULLS LAST,source_priority ASC,witness_key ASC) FILTER (WHERE rank_clean IS NOT NULL))[1] AS rank,
  (array_agg(cred_clean ORDER BY hearing_date DESC NULLS LAST,source_priority ASC,witness_key ASC) FILTER (WHERE cred_clean IS NOT NULL))[1] AS credentials,
  (array_agg(org_clean ORDER BY hearing_date DESC NULLS LAST,source_priority ASC,witness_key ASC) FILTER (WHERE org_clean IS NOT NULL))[1] AS organization,
  CASE
   WHEN bool_or(grouping_basis='reviewed') THEN 'reviewed'
   WHEN bool_or(grouping_basis='bioguide') THEN 'bioguide'
   WHEN bool_or(grouping_basis='name_organization') THEN 'name_organization'
   ELSE 'singleton'
  END AS grouping_basis,
  cast(count(*) AS INT) AS appearance_count,
  min(hearing_date) AS first_seen_date,
  max(hearing_date) AS last_seen_date,
  array_agg(witness_key ORDER BY witness_key) AS witness_keys
 FROM shown
 GROUP BY person_key
), hearings_agg AS (
 SELECT person_key,cast(count(*) AS INT) AS hearing_count
 FROM (SELECT DISTINCT person_key,occasion FROM shown)
 GROUP BY person_key
), variants_agg AS (
 SELECT person_key,array_agg(name_clean ORDER BY name_clean) AS name_variants
 FROM (SELECT DISTINCT person_key,name_clean FROM shown WHERE name_clean IS NOT NULL AND name_clean<>'')
 GROUP BY person_key
), ranks_agg AS (
 SELECT person_key,array_agg(rank_clean ORDER BY rank_clean) AS ranks
 FROM (SELECT DISTINCT person_key,rank_clean FROM shown WHERE rank_clean IS NOT NULL)
 GROUP BY person_key
), orgs_agg AS (
 SELECT person_key,array_agg(org_clean ORDER BY org_clean) AS organizations
 FROM (SELECT DISTINCT person_key,org_clean FROM shown WHERE org_clean IS NOT NULL)
 GROUP BY person_key
), pos_agg AS (
 SELECT person_key,array_agg(pos_clean ORDER BY pos_clean) AS positions
 FROM (SELECT DISTINCT person_key,pos_clean FROM shown WHERE pos_clean IS NOT NULL)
 GROUP BY person_key
)
SELECT
 b.person_key,
 CASE WHEN b.grouping_basis='bioguide' THEN b.person_key END AS bioguide_id,
 b.name,
 b.rank,
 coalesce(ra.ranks,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS ranks,
 b.credentials,
 coalesce(va.name_variants,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS name_variants,
 b.organization,
 coalesce(oa.organizations,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS organizations,
 coalesce(pa.positions,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS positions,
 b.grouping_basis,
 b.appearance_count,
 ha.hearing_count,
 b.first_seen_date,
 b.last_seen_date,
 b.witness_keys
FROM ranks_agg ra
RIGHT JOIN (
 pos_agg pa
 RIGHT JOIN (
  orgs_agg oa
  RIGHT JOIN (
   variants_agg va
   RIGHT JOIN (
    hearings_agg ha
    JOIN base_agg b ON ha.person_key=b.person_key
   ) ON va.person_key=b.person_key
  ) ON oa.person_key=b.person_key
 ) ON pa.person_key=b.person_key
) ON ra.person_key=b.person_key
