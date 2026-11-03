WITH seed_bills AS (
 SELECT DISTINCT lower(trim(unnest(measure_keys))) AS bill_id FROM ordered WHERE measure_keys IS NOT NULL
 UNION
 SELECT DISTINCT lower(trim(unnest(subject_keys))) AS bill_id FROM meetings_resolved WHERE subject_keys IS NOT NULL
 UNION
 SELECT DISTINCT lower(trim(unnest(subject_keys))) AS bill_id FROM meetings_export WHERE subject_keys IS NOT NULL
 UNION
 SELECT DISTINCT lower(trim(bill_id)) AS bill_id
 FROM spicy_congress_bills
 WHERE bill_id IS NOT NULL
   AND try_cast(split_part(lower(trim(bill_id)),'-',1) AS INT)>=113
   AND ((public_law_number IS NOT NULL AND trim(public_law_number)<>'') OR coalesce(try_cast(cosponsor_count AS INT),0)>=10)
 UNION
 SELECT DISTINCT lower(trim(bill_id)) AS bill_id
 FROM spicy_bill_committee_activities
 WHERE bill_id IS NOT NULL
   AND try_cast(split_part(lower(trim(bill_id)),'-',1) AS INT)>=113
   AND activity_name IS NOT NULL
   AND NOT regexp_like(lower(trim(activity_name)),'^referred')
 UNION
 SELECT DISTINCT lower(trim(bill_id)) AS bill_id
 FROM spicy_cbo_cost_estimates
 WHERE bill_id IS NOT NULL
   AND try_cast(split_part(lower(trim(bill_id)),'-',1) AS INT)>=113
 UNION
 SELECT DISTINCT lower(trim(bill_id)) AS bill_id
 FROM spicy_roll_call_votes
 WHERE bill_id IS NOT NULL AND trim(bill_id)<>''
   AND try_cast(split_part(lower(trim(bill_id)),'-',1) AS INT)>=113
 UNION
 SELECT DISTINCT lower(trim(bill_id)) AS bill_id
 FROM spicy_bill_vote_references
 WHERE bill_id IS NOT NULL AND trim(bill_id)<>''
   AND try_cast(split_part(lower(trim(bill_id)),'-',1) AS INT)>=113
), related_bill_unnested AS (
 SELECT
  lower(trim(cb.bill_id)) AS source_bill_id,
  lower(trim(r['congress']))||'-'||lower(trim(r['bill_type']))||'-'||lower(trim(r['number'])) AS target_bill_id,
  nullif(trim(r['title']),'') AS target_title,
  r['relationship_details'] AS relationship_details
 FROM (
  SELECT bill_id,unnest(related_bills) AS r
  FROM spicy_congress_bills
  WHERE bill_id IS NOT NULL AND related_bills IS NOT NULL AND coalesce(array_length(related_bills),0)>0
 ) cb
 WHERE r['congress'] IS NOT NULL AND trim(r['congress'])<>''
   AND r['bill_type'] IS NOT NULL AND trim(r['bill_type'])<>''
   AND r['number'] IS NOT NULL AND trim(r['number'])<>''
), referenced_bills AS (
 SELECT DISTINCT bill_id FROM seed_bills WHERE bill_id IS NOT NULL AND bill_id<>''
 UNION
 SELECT DISTINCT e.target_bill_id AS bill_id
 FROM related_bill_unnested e
 JOIN seed_bills s ON s.bill_id=e.source_bill_id
 UNION
 SELECT DISTINCT e.source_bill_id AS bill_id
 FROM related_bill_unnested e
 JOIN seed_bills s ON s.bill_id=e.target_bill_id
), related_bills_filtered AS (
 SELECT e.source_bill_id,e.target_bill_id,e.target_title,e.relationship_details
 FROM related_bill_unnested e
 JOIN referenced_bills rb ON rb.bill_id=e.source_bill_id
), related_bill_types AS (
 SELECT
  source_bill_id,
  target_bill_id,
  nullif(trim(rd['type']),'') AS rel_type
 FROM (
  SELECT source_bill_id,target_bill_id,unnest(relationship_details) AS rd
  FROM related_bills_filtered
  WHERE relationship_details IS NOT NULL AND coalesce(array_length(relationship_details),0)>0
 )
 WHERE nullif(trim(rd['type']),'') IS NOT NULL
), related_bill_types_agg AS (
 SELECT
  source_bill_id,
  target_bill_id,
  array_sort(array_distinct(array_agg(rel_type))) AS relationship_types
 FROM related_bill_types
 GROUP BY source_bill_id,target_bill_id
), related_bills_dedup AS (
 SELECT
  f.source_bill_id,
  f.target_bill_id,
  max(f.target_title) AS title,
  coalesce(
   t.relationship_types,
   arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
  ) AS relationship_types
 FROM related_bills_filtered f
 LEFT JOIN related_bill_types_agg t
  ON t.source_bill_id=f.source_bill_id AND t.target_bill_id=f.target_bill_id
 GROUP BY f.source_bill_id,f.target_bill_id,t.relationship_types
), related_bills_sorted AS (
 SELECT *,row_number() OVER (
  PARTITION BY source_bill_id
  ORDER BY target_bill_id ASC
 ) AS rel_seq
 FROM related_bills_dedup
), related_bills_agg AS (
 SELECT source_bill_id AS bill_id,
  array_agg(named_struct(
   'bill_id',target_bill_id,
   'title',title,
   'relationship_types',relationship_types
  ) ORDER BY rel_seq ASC) AS related_bills
 FROM related_bills_sorted
 GROUP BY source_bill_id
), bill_committees_agg AS (
 SELECT lower(trim(c.bill_id)) AS bill_id,
  array_sort(array_distinct(array_agg(lower(trim(c.system_code))))) AS committees
 FROM spicy_bill_committees c
 JOIN referenced_bills rb ON lower(trim(c.bill_id))=rb.bill_id
 WHERE c.bill_id IS NOT NULL AND c.system_code IS NOT NULL
 GROUP BY lower(trim(c.bill_id))
), cbo_parsed AS (
 SELECT lower(trim(c.bill_id)) AS bill_id,
  c.publication_id,
  coalesce(try_cast(c.pub_date AS DATE),cast(arrow_cast(try_cast(c.pub_date AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)) AS pub_date,
  c.description
 FROM spicy_cbo_cost_estimates c
 JOIN referenced_bills rb ON lower(trim(c.bill_id))=rb.bill_id
 WHERE c.bill_id IS NOT NULL
), cbo_sorted AS (
 SELECT *,row_number() OVER (
  PARTITION BY bill_id
  ORDER BY pub_date ASC NULLS LAST,publication_id ASC
 ) AS cbo_seq
 FROM cbo_parsed
), cbo_agg AS (
 SELECT bill_id,
  array_agg(named_struct(
   'publication_id',publication_id,
   'date',pub_date,
   'description',description
  ) ORDER BY cbo_seq ASC) AS cbo_estimates
 FROM cbo_sorted
 GROUP BY bill_id
), raw_votes AS (
 SELECT lower(trim(v.bill_id)) AS bill_id,
  v.vote_id,'vote_record' AS basis,
  CASE lower(trim(v.chamber)) WHEN 'h' THEN 'house' WHEN 's' THEN 'senate' ELSE lower(trim(v.chamber)) END AS chamber,
  coalesce(try_cast(v.vote_day AS DATE),cast(arrow_cast(try_cast(v.vote_day AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)) AS vote_date,
  v.question,v.result,try_cast(v.yea AS SMALLINT) AS yea,try_cast(v.nay AS SMALLINT) AS nay,
  1 AS basis_rank
 FROM spicy_roll_call_votes v
 JOIN referenced_bills rb ON lower(trim(v.bill_id))=rb.bill_id
 WHERE v.bill_id IS NOT NULL AND trim(v.bill_id)<>''
 UNION ALL
 SELECT lower(trim(r.bill_id)) AS bill_id,
  v.vote_id,'bill_action' AS basis,
  CASE lower(trim(v.chamber)) WHEN 'h' THEN 'house' WHEN 's' THEN 'senate' ELSE lower(trim(v.chamber)) END AS chamber,
  coalesce(try_cast(v.vote_day AS DATE),cast(arrow_cast(try_cast(v.vote_day AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)) AS vote_date,
  v.question,v.result,try_cast(v.yea AS SMALLINT) AS yea,try_cast(v.nay AS SMALLINT) AS nay,
  2 AS basis_rank
 FROM spicy_bill_vote_references r
 JOIN referenced_bills rb ON lower(trim(r.bill_id))=rb.bill_id
 JOIN spicy_roll_call_votes v
  ON cast(v.congress AS VARCHAR)=cast(r.congress AS VARCHAR)
  AND (CASE lower(trim(v.chamber)) WHEN 'h' THEN 'house' WHEN 's' THEN 'senate' ELSE lower(trim(v.chamber)) END)
    = (CASE lower(trim(r.chamber)) WHEN 'h' THEN 'house' WHEN 's' THEN 'senate' ELSE lower(trim(r.chamber)) END)
  AND cast(v.session AS VARCHAR)=cast(r.session AS VARCHAR)
  AND cast(v.roll_number AS VARCHAR)=cast(r.roll_number AS VARCHAR)
 WHERE r.bill_id IS NOT NULL
), dedup_votes AS (
 SELECT *,row_number() OVER(PARTITION BY bill_id,vote_id ORDER BY basis_rank ASC) AS rn
 FROM raw_votes WHERE vote_id IS NOT NULL
), votes_sorted AS (
 SELECT *,row_number() OVER (
  PARTITION BY bill_id
  ORDER BY vote_date ASC NULLS LAST,vote_id ASC
 ) AS vote_seq
 FROM dedup_votes WHERE rn=1
), votes_agg AS (
 SELECT bill_id,array_agg(named_struct(
  'vote_id',vote_id,'basis',basis,'chamber',chamber,'date',vote_date,
  'question',question,'result',result,'yea',yea,'nay',nay
 ) ORDER BY vote_seq ASC) AS floor_votes
 FROM votes_sorted GROUP BY bill_id
), amdt_base AS (
 SELECT lower(trim(amendment_id)) AS amendment_id,purpose,sponsor_bioguide_id,
  coalesce(try_cast(latest_action_date AS DATE),cast(arrow_cast(try_cast(latest_action_date AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)) AS latest_action_date,
  latest_action_text,
  lower(nullif(trim(amended_bill_id),'')) AS amended_bill_id,
  lower(nullif(trim(amended_amendment_id),'')) AS amended_amendment_id
 FROM spicy_amendments WHERE amendment_id IS NOT NULL
), amdt_resolved AS (
 SELECT coalesce(a0.amended_bill_id,a1.amended_bill_id,a2.amended_bill_id,a3.amended_bill_id) AS bill_id,
  a0.amendment_id,a0.purpose,a0.sponsor_bioguide_id,a0.latest_action_date,a0.latest_action_text
 FROM amdt_base a0
 LEFT JOIN amdt_base a1 ON a0.amended_bill_id IS NULL AND a0.amended_amendment_id=a1.amendment_id
 LEFT JOIN amdt_base a2 ON a0.amended_bill_id IS NULL AND a1.amended_bill_id IS NULL AND a1.amended_amendment_id=a2.amendment_id
 LEFT JOIN amdt_base a3 ON a0.amended_bill_id IS NULL AND a1.amended_bill_id IS NULL AND a2.amended_bill_id IS NULL AND a2.amended_amendment_id=a3.amendment_id
), amdt_dedup AS (
 SELECT DISTINCT ar.*
 FROM amdt_resolved ar
 JOIN referenced_bills rb ON ar.bill_id=rb.bill_id
 WHERE ar.bill_id IS NOT NULL
), amdt_sorted AS (
 SELECT *,row_number() OVER (
  PARTITION BY bill_id
  ORDER BY latest_action_date ASC NULLS LAST,amendment_id ASC
 ) AS amdt_seq
 FROM amdt_dedup
), amendments_agg AS (
 SELECT bill_id,array_agg(named_struct(
  'amendment_id',amendment_id,'purpose',purpose,'sponsor_bioguide_id',sponsor_bioguide_id,
  'latest_action_date',latest_action_date,'latest_action_text',latest_action_text
 ) ORDER BY amdt_seq ASC) AS amendments
 FROM amdt_sorted GROUP BY bill_id
), activities_parsed AS (
 SELECT lower(trim(a.bill_id)) AS bill_id,
  lower(trim(a.system_code)) AS system_code,
  a.activity_name AS activity,
  coalesce(try_cast(a.activity_date AS DATE),cast(arrow_cast(try_cast(a.activity_date AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)) AS act_date,
  coalesce(a.occurrence,0) AS occurrence
 FROM spicy_bill_committee_activities a
 JOIN referenced_bills rb ON lower(trim(a.bill_id))=rb.bill_id
 WHERE a.bill_id IS NOT NULL AND a.system_code IS NOT NULL AND a.activity_name IS NOT NULL
), activities_sorted AS (
 SELECT *,row_number() OVER (
  PARTITION BY bill_id
  ORDER BY act_date ASC NULLS LAST,occurrence ASC,system_code ASC,activity ASC
 ) AS act_seq
 FROM activities_parsed
), activities_agg AS (
 SELECT bill_id,array_agg(named_struct(
  'system_code',system_code,'activity',activity,'date',act_date
 ) ORDER BY act_seq ASC) AS committee_activities
 FROM activities_sorted GROUP BY bill_id
), base_bills AS (
 SELECT lower(trim(bill_id)) AS norm_bill_id,
  title,short_title,
  nullif(trim(sponsor_bioguide_id),'') AS sponsor_bioguide_id,
  coalesce(try_cast(introduced_date AS DATE),cast(arrow_cast(try_cast(introduced_date AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)) AS introduced,
  coalesce(try_cast(latest_action_date AS DATE),cast(arrow_cast(try_cast(latest_action_date AS TIMESTAMP WITH TIME ZONE),'Timestamp(Second, Some("America/New_York"))') AS DATE)) AS latest_action_date,
  latest_action_text,
  nullif(trim(stage),'') AS stage,
  nullif(trim(policy_area),'') AS policy_area,
  nullif(trim(public_law_number),'') AS public_law_number,
  try_cast(cosponsor_count AS INT) AS cosponsor_count
 FROM spicy_congress_bills WHERE bill_id IS NOT NULL
)
SELECT b.norm_bill_id AS bill_id,
 b.title,b.short_title,
 b.sponsor_bioguide_id,
 b.introduced,
 b.latest_action_date,
 b.latest_action_text,
 b.stage,
 b.policy_area,
 b.public_law_number,
 b.cosponsor_count,
 coalesce(rel.related_bills,array_slice(make_array(named_struct(
  'bill_id',cast(NULL AS VARCHAR),
  'title',cast(NULL AS VARCHAR),
  'relationship_types',arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
 )),1,0)) AS related_bills,
 coalesce(c.committees,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS committees,
 coalesce(cbo.cbo_estimates,array_slice(make_array(named_struct(
  'publication_id',cast(NULL AS VARCHAR),'date',cast(NULL AS DATE),'description',cast(NULL AS VARCHAR)
 )),1,0)) AS cbo_estimates,
 coalesce(v.floor_votes,array_slice(make_array(named_struct(
  'vote_id',cast(NULL AS VARCHAR),'basis',cast(NULL AS VARCHAR),'chamber',cast(NULL AS VARCHAR),
  'date',cast(NULL AS DATE),'question',cast(NULL AS VARCHAR),'result',cast(NULL AS VARCHAR),
  'yea',cast(NULL AS SMALLINT),'nay',cast(NULL AS SMALLINT)
 )),1,0)) AS floor_votes,
 coalesce(a.amendments,array_slice(make_array(named_struct(
  'amendment_id',cast(NULL AS VARCHAR),'purpose',cast(NULL AS VARCHAR),'sponsor_bioguide_id',cast(NULL AS VARCHAR),
  'latest_action_date',cast(NULL AS DATE),'latest_action_text',cast(NULL AS VARCHAR)
 )),1,0)) AS amendments,
 coalesce(act.committee_activities,array_slice(make_array(named_struct(
  'system_code',cast(NULL AS VARCHAR),'activity',cast(NULL AS VARCHAR),'date',cast(NULL AS DATE)
 )),1,0)) AS committee_activities
FROM base_bills b
JOIN referenced_bills rb ON b.norm_bill_id=rb.bill_id
LEFT JOIN related_bills_agg rel ON b.norm_bill_id=rel.bill_id
LEFT JOIN bill_committees_agg c ON b.norm_bill_id=c.bill_id
LEFT JOIN cbo_agg cbo ON b.norm_bill_id=cbo.bill_id
LEFT JOIN votes_agg v ON b.norm_bill_id=v.bill_id
LEFT JOIN amendments_agg a ON b.norm_bill_id=a.bill_id
LEFT JOIN activities_agg act ON b.norm_bill_id=act.bill_id
