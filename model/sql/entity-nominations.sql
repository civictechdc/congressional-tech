WITH referenced_nominations AS (
 SELECT DISTINCT lower(trim(unnest(subject_keys))) AS nomination_id FROM meetings_resolved WHERE subject_keys IS NOT NULL
 UNION
 SELECT DISTINCT lower(trim(unnest(measure_keys))) AS nomination_id FROM ordered WHERE measure_keys IS NOT NULL
), keyed_nominations AS (
 SELECT
  cast(congress AS VARCHAR)||'-pn-'||cast(number AS VARCHAR)||
  CASE WHEN part_number IS NOT NULL AND try_cast(part_number AS INT) IS NOT NULL AND try_cast(part_number AS INT)<>0
       THEN '-'||cast(try_cast(part_number AS INT) AS VARCHAR) ELSE '' END AS nomination_id,
  congress,number,part_number,description,organization,received_date,
  latest_action_date,latest_action_text,committees_json,hearings_json
 FROM spicy_nominations WHERE congress IS NOT NULL AND number IS NOT NULL
), matched_nominations AS (
 SELECT k.* FROM keyed_nominations k
 JOIN referenced_nominations r ON k.nomination_id=r.nomination_id
), committee_chunks AS (
 SELECT nomination_id,unnest(string_to_array(committees_json,'}')) AS chunk
 FROM matched_nominations WHERE committees_json IS NOT NULL
), committee_extracted AS (
 SELECT nomination_id,
  lower(coalesce(
   (regexp_match(chunk,'(?i)"system_?code"\s*:\s*"([^"]+)"'))[1],
   (regexp_match(chunk,'"([a-zA-Z]{4}[0-9]{2})"'))[1]
  )) AS system_code
 FROM committee_chunks
), committees_agg AS (
 SELECT nomination_id,array_sort(array_distinct(array_agg(system_code))) AS committees
 FROM committee_extracted WHERE system_code IS NOT NULL AND system_code<>''
 GROUP BY nomination_id
), hearing_chunks AS (
 SELECT nomination_id,congress,unnest(string_to_array(hearings_json,'}')) AS chunk
 FROM matched_nominations WHERE hearings_json IS NOT NULL
), hearing_extracted AS (
 SELECT nomination_id,
  coalesce(
   (regexp_match(chunk,'(CHRG-[0-9]+[hsj]hrg[0-9]+)'))[1],
   CASE WHEN regexp_like(chunk,'(?i)"jacket(?:_?number)?"\s*:\s*"?([0-9]+)"?')
    THEN 'CHRG-'||cast(congress AS VARCHAR)||
     (CASE lower(coalesce((regexp_match(chunk,'(?i)"chamber"\s*:\s*"([^"]+)"'))[1],'senate'))
      WHEN 'house' THEN 'h' WHEN 'joint' THEN 'j' ELSE 's' END)||'hrg'||
     (regexp_match(chunk,'(?i)"jacket(?:_?number)?"\s*:\s*"?([0-9]+)"?'))[1]
   END
  ) AS package_id
 FROM hearing_chunks
), transcripts_agg AS (
 SELECT nomination_id,array_sort(array_distinct(array_agg(package_id))) AS transcripts
 FROM hearing_extracted WHERE package_id IS NOT NULL AND package_id<>''
 GROUP BY nomination_id
), vote_docs AS (
 SELECT v.vote_id,v.congress AS vote_congress,v.chamber,v.vote_day,v.question,v.result,v.yea,v.nay,
  unnest(v.documents) AS doc
 FROM spicy_roll_call_votes v
 WHERE v.documents IS NOT NULL AND lower(trim(v.chamber)) IN ('s','senate')
), pn_votes AS (
 SELECT DISTINCT
  coalesce(cast(doc['congress'] AS VARCHAR),cast(vote_congress AS VARCHAR))||'-pn-'||
  regexp_replace(
   regexp_replace(
    regexp_replace(lower(trim(doc['number'])),'^(?:pn\s*)?0*([0-9]+)', '$1'),
    '-0+([1-9][0-9]*)$','-$1'
   ),
   '-0+$',''
  ) AS nomination_id,
  vote_id,
  coalesce(try_cast(vote_day AS DATE),cast(arrow_cast(try_cast(vote_day AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)) AS vote_date,
  question,result,try_cast(yea AS SMALLINT) AS yea,try_cast(nay AS SMALLINT) AS nay
 FROM vote_docs
 WHERE upper(trim(doc['type']))='PN' AND doc['number'] IS NOT NULL
), pn_votes_matched AS (
 SELECT pv.*
 FROM pn_votes pv
 JOIN matched_nominations mn ON pv.nomination_id=mn.nomination_id
), pn_votes_sorted AS (
 SELECT *,row_number() OVER (
  PARTITION BY nomination_id
  ORDER BY vote_date ASC NULLS LAST,vote_id ASC
 ) AS vote_seq
 FROM pn_votes_matched
), votes_agg AS (
 SELECT nomination_id,array_agg(named_struct(
  'vote_id',vote_id,'date',vote_date,'question',question,'result',result,'yea',yea,'nay',nay
 ) ORDER BY vote_seq ASC) AS floor_votes
 FROM pn_votes_sorted GROUP BY nomination_id
)
SELECT m.nomination_id,
 m.description,m.organization,
 coalesce(try_cast(m.received_date AS DATE),cast(arrow_cast(try_cast(m.received_date AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)) AS received,
 coalesce(try_cast(m.latest_action_date AS DATE),cast(arrow_cast(try_cast(m.latest_action_date AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)) AS latest_action_date,
 m.latest_action_text,
 coalesce(c.committees,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS committees,
 coalesce(t.transcripts,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS transcripts,
 coalesce(v.floor_votes,array_slice(make_array(named_struct(
  'vote_id',cast(NULL AS VARCHAR),'date',cast(NULL AS DATE),'question',cast(NULL AS VARCHAR),
  'result',cast(NULL AS VARCHAR),'yea',cast(NULL AS SMALLINT),'nay',cast(NULL AS SMALLINT)
 )),1,0)) AS floor_votes
FROM matched_nominations m
LEFT JOIN committees_agg c ON m.nomination_id=c.nomination_id
LEFT JOIN transcripts_agg t ON m.nomination_id=t.nomination_id
LEFT JOIN votes_agg v ON m.nomination_id=v.nomination_id
