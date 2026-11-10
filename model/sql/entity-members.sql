WITH ranked_terms AS (
 SELECT *,row_number() OVER (
  PARTITION BY bioguide_id
  ORDER BY start_date DESC NULLS LAST,end_date DESC NULLS LAST,chamber ASC
 ) AS term_seq
 FROM member_terms
), terms_agg AS (
 SELECT bioguide_id,array_agg(named_struct(
  'chamber',chamber,'state',state,'district',district,'party',party,'start',start_date,'end',end_date
 ) ORDER BY term_seq ASC) AS terms
 FROM ranked_terms GROUP BY bioguide_id
)
SELECT m.bioguide_id,
 trim(coalesce(m.name_first,'')||' '||coalesce(m.name_last,'')) AS name,
 coalesce(t.terms,array_slice(make_array(named_struct(
  'chamber',cast(NULL AS VARCHAR),'state',cast(NULL AS VARCHAR),'district',cast(NULL AS SMALLINT),
  'party',cast(NULL AS VARCHAR),'start',cast(NULL AS DATE),'end',cast(NULL AS DATE)
 )),1,0)) AS terms,
 named_struct(
  'lis',nullif(trim(cast(m.lis_id AS VARCHAR)),''),
  'opensecrets',nullif(trim(cast(m.opensecrets_id AS VARCHAR)),''),
  'govtrack',nullif(trim(cast(m.govtrack_id AS VARCHAR)),''),
  'icpsr',nullif(trim(cast(m.icpsr_id AS VARCHAR)),''),
  'wikidata',nullif(trim(cast(m.wikidata_id AS VARCHAR)),''),
  'fec',coalesce(m.fec_ids,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))
 ) AS cross_ids
FROM spicy_members m
LEFT JOIN terms_agg t ON m.bioguide_id=t.bioguide_id
WHERE m.bioguide_id IS NOT NULL
