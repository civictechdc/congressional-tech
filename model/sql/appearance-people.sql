-- One person key per stated appearance: family name and first initial from the parser's name_key, with
-- honorifics and suffixes dropped. Print entries the parser labels statements are not people. Shared by
-- print-to-meeting agreement (witness overlap) and per-person precedence in appearance resolution.
WITH rows AS (
 SELECT r.record_sha_hex,r.source,r.event_id,nullif(trim(r.package_id),'') AS print_id,
  unnest(r.appearances) AS a,unnest(range(0,cast(array_length(r.appearances) AS BIGINT))) AS ordinal
 FROM selected_appearance_records r
 WHERE r.status='completed' AND r.appearances IS NOT NULL AND coalesce(array_length(r.appearances),0)>0
), tokens AS (
 SELECT record_sha_hex,source,event_id,print_id AS package_id,ordinal,a['witness_type'] AS witness_type,
  array_except(string_to_array(trim(regexp_replace(lower(coalesce(a['name_key'],'')),'[^a-z ]+','','g')),' '),
   make_array('','mr','mrs','ms','miss','mx','dr','hon','honorable','the','rev','sen','senator','rep','representative',
    'gen','general','lt','col','maj','adm','capt','sgt','jr','sr','ii','iii','iv','phd','md','esq','ret','usa','usn','usaf','usmc')) AS t
 FROM rows
)
SELECT record_sha_hex,source,event_id,package_id,ordinal,
 coalesce(witness_type IN ('statement_for_record','member_statement'),false) AS statement,
 CASE WHEN cardinality(t)>0 THEN t[cast(cardinality(t) AS BIGINT)] END AS family,
 CASE WHEN cardinality(t)>1 THEN substr(t[1],1,1) END AS initial
FROM tokens
