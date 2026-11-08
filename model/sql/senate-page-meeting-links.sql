-- Link present Senate committee hearing pages (senate_page) to canonical meetings (ct-j2yo).
-- Pages resolve by parent committee (.senate.gov host) and hearing date (a labeled
-- Banking hearing date, page_facts.content_date, bracketed [YYYY-MM-DD] in title,
-- URL date tokens, or written Month DD, YYYY in text_head),
-- disambiguated across same-day committee meetings by witness surname overlap (with MODS / Congress.gov)
-- and substantive title/slug word overlap.
-- Empty or absent senate_page containers are excluded so they never suppress MODS witnesses.
WITH stopwords AS (
 SELECT make_array(
  '','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that',
  'hearing','hearings','subcommittee','committee','senate','united','states','congress','washington','full','open','closed',
  'session','examine','examining','review','oversight','part','http','https','www','gov','html','htm','imo','media','doc','pdf','download','watch','live'
 ) AS sw
), senate_candidates AS (
 SELECT DISTINCT r.record_sha_hex,r.context_url,
  arrow_cast(decode(r.record_sha_hex,'hex'),'FixedSizeBinary(32)') AS sha256
 FROM selected_appearance_records r
 JOIN (SELECT DISTINCT record_sha_hex FROM appearance_people WHERE source='senate_page') ap
  ON ap.record_sha_hex=r.record_sha_hex
 WHERE r.source='senate_page' AND r.status='completed'
  AND coalesce(nullif(trim(r.collection_state),''),'present')='present'
), capture_urls AS (
 SELECT sc.record_sha_hex,
  coalesce(c.url,c.requested_url,c.context_url) AS source_url
 FROM captures c
 JOIN senate_candidates sc ON c.sha256=sc.sha256
 WHERE c.mode='fetch' AND c.complete AND c.outcome IN ('stored','unchanged')
  AND c.http_status BETWEEN 200 AND 299 AND c.sha256 IS NOT NULL
 GROUP BY sc.record_sha_hex,coalesce(c.url,c.requested_url,c.context_url)
), senate_hosts AS (
 SELECT DISTINCT
  lower((regexp_match(website_url,'(?i)^https?://(?:www[.])?([a-z0-9-]+)[.]senate[.]gov'))[1]) AS host,
  CASE WHEN lower(system_code)='jsec00' THEN 'jjec00'
   ELSE substr(lower(system_code),1,4)||'00' END AS parent_committee
 FROM spicy_committees
 WHERE parent_system_code IS NULL
  AND regexp_like(coalesce(website_url,''),'(?i)^https?://(?:www[.])?[a-z0-9-]+[.]senate[.]gov')
 UNION
 SELECT 'aging' AS host,'spag00' AS parent_committee
 UNION SELECT 'ag','ssaf00'
 UNION SELECT 'agriculture','ssaf00'
 UNION SELECT 'appropriations','ssap00'
 UNION SELECT 'armed-services','ssas00'
 UNION SELECT 'banking','ssbk00'
 UNION SELECT 'budget','ssbu00'
 UNION SELECT 'commerce','sscm00'
 UNION SELECT 'drugcaucus','scnc00'
 UNION SELECT 'energy','sseg00'
 UNION SELECT 'epw','ssev00'
 UNION SELECT 'ethics','slet00'
 UNION SELECT 'finance','ssfi00'
 UNION SELECT 'foreign','ssfr00'
 UNION SELECT 'help','sshr00'
 UNION SELECT 'hsgac','ssga00'
 UNION SELECT 'indian','slia00'
 UNION SELECT 'intelligence','slin00'
 UNION SELECT 'judiciary','ssju00'
 UNION SELECT 'rules','ssra00'
 UNION SELECT 'sbc','sssb00'
 UNION SELECT 'veterans','ssva00'
 UNION SELECT 'jec','jjec00'
), senate_pages_raw AS (
 SELECT
  sc.record_sha_hex,
  coalesce(cu.source_url,sc.context_url) AS source_url,
  sh.parent_committee,
  coalesce(pf.heading,'')||' '||coalesce(pf.title,'')||' '||
   regexp_replace(coalesce(cu.source_url,sc.context_url,''),'^https?://[^/]+/','') AS page_text,
  try_cast(pf.content_date AS DATE) AS pf_date,
  try_cast((regexp_match(coalesce(pf.title,''),'\[([0-9]{4}-[0-9]{2}-[0-9]{2})\]'))[1] AS DATE) AS title_bracket_date,
  try_cast((regexp_match(coalesce(cu.source_url,sc.context_url,''),'/([0-9]{4}-[0-9]{2}-[0-9]{2})(?:[^0-9]|$)'))[1] AS DATE) AS url_iso_date,
  regexp_match(coalesce(cu.source_url,sc.context_url,''),'/([0-9]{2})[/-]([0-9]{2})[/-]([0-9]{4})(?:[^0-9]|$)') AS url_mdy,
  regexp_match(coalesce(cu.source_url,sc.context_url,''),'/([0-9]{2})-([0-9]{2})-([0-9]{2})-[a-zA-Z]') AS url_mdy2,
  coalesce(pf.text_head,'') AS text_head,
  CASE WHEN regexp_like(coalesce(cu.source_url,sc.context_url,''),'(?i)^https?://(?:www[.])?banking[.]senate[.]gov/hearings/')
   THEN coalesce(cu.source_url,sc.context_url) END AS banking_hearing_url
 FROM senate_candidates sc
 LEFT JOIN capture_urls cu ON cu.record_sha_hex=sc.record_sha_hex
 LEFT JOIN page_facts pf ON pf.body_sha=sc.sha256 AND pf.status='completed'
 JOIN senate_hosts sh ON sh.host=lower((regexp_match(coalesce(cu.source_url,sc.context_url,''),'(?i)^https?://(?:www[.])?([a-z0-9-]+)[.]senate[.]gov'))[1])
), senate_text_dates AS (
 SELECT r.*,
  try_cast(text_mdy[3]||'-'||lpad(cast(array_position(months,lower(text_mdy[1])) AS VARCHAR),2,'0')
   ||'-'||lpad(text_mdy[2],2,'0') AS DATE) AS text_date,
  try_cast(labeled_mdy[3]||'-'||lpad(cast(array_position(months,lower(labeled_mdy[1])) AS VARCHAR),2,'0')
   ||'-'||lpad(labeled_mdy[2],2,'0') AS DATE) AS labeled_date
 FROM (
  SELECT *,
   make_array('january','february','march','april','may','june','july','august','september','october','november','december') AS months,
   regexp_match(text_head,'(?i)\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-9]{1,2}),\s*([0-9]{4})\b') AS text_mdy,
   CASE WHEN banking_hearing_url IS NOT NULL
    THEN regexp_match(text_head,'(?i)\bDate:\s*(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*)?(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-9]{1,2}),\s*([0-9]{4})\s+Time:')
   END AS labeled_mdy
  FROM senate_pages_raw
 ) r
), senate_pages_grouped AS (
 SELECT
  r.record_sha_hex,
  min(r.source_url) AS source_url,
  min(r.banking_hearing_url) AS banking_hearing_url,
  r.parent_committee,
  -- The displayed date is a body fact. Select it across the whole group
  -- before considering dates from individual addresses.
  coalesce(min(r.labeled_date),min(coalesce(
   r.pf_date,
   r.title_bracket_date,
   r.url_iso_date,
   CASE WHEN r.url_mdy IS NOT NULL THEN try_cast(r.url_mdy[3]||'-'||r.url_mdy[1]||'-'||r.url_mdy[2] AS DATE) END,
   CASE WHEN r.url_mdy2 IS NOT NULL THEN try_cast('20'||r.url_mdy2[3]||'-'||r.url_mdy2[1]||'-'||r.url_mdy2[2] AS DATE) END,
   r.text_date
  ))) AS page_date,
  min(r.page_text) AS page_text
 FROM senate_text_dates r
 GROUP BY r.record_sha_hex,r.parent_committee
), senate_pages AS (
 SELECT
  g.record_sha_hex,
  g.source_url,
  g.banking_hearing_url,
  g.parent_committee,
  g.page_date,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(g.page_text),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|[0-9]+)\b',' ','g')),' '),
   sw.sw
  )) AS words,
  first_value(g.source_url) OVER (PARTITION BY g.page_date,g.parent_committee ORDER BY g.source_url ASC,g.record_sha_hex ASC)=
   first_value(g.source_url) OVER (PARTITION BY g.page_date,g.parent_committee ORDER BY g.source_url DESC,g.record_sha_hex ASC) AS single_url_on_date
 FROM senate_pages_grouped g
 CROSS JOIN stopwords sw
 WHERE g.page_date IS NOT NULL
), meeting_committee_codes AS (
 SELECT event_id,meeting_date,title,chamber,substr(lower(c['system_code']),1,4)||'00' AS parent_committee
 FROM (
  SELECT event_id,meeting_date,title,chamber,unnest(committees) AS c
  FROM meetings_resolved
  WHERE (chamber IN ('senate','joint') OR chamber IS NULL) AND meeting_date IS NOT NULL
   AND NOT coalesce(not_held,false) AND committees IS NOT NULL
 )
 WHERE c['system_code'] IS NOT NULL AND trim(c['system_code'])<>''
 UNION ALL
 SELECT event_id,meeting_date,title,chamber,substr(lower(committee_key),1,4)||'00' AS parent_committee
 FROM meetings_resolved
 WHERE (chamber IN ('senate','joint') OR chamber IS NULL) AND meeting_date IS NOT NULL
  AND NOT coalesce(not_held,false) AND committee_key IS NOT NULL AND trim(committee_key)<>''
), raw_meeting_committees AS (
 -- The JEC site and reference data use both codes for the same committee.
 -- Keep that equivalence local to page matching, including source-backed
 -- events with no stated chamber. Require corroboration for those events.
 SELECT DISTINCT event_id,meeting_date,title,chamber IS NULL AS requires_overlap,
  CASE WHEN parent_committee='jsec00' THEN 'jjec00' ELSE parent_committee END AS parent_committee
 FROM meeting_committee_codes
 WHERE chamber IS NOT NULL OR parent_committee IN ('jjec00','jsec00')
), meeting_parent_committees AS (
 SELECT
  m.event_id,
  m.meeting_date,
  m.parent_committee,
  m.requires_overlap,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(m.title,'')),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|[0-9]+)\b',' ','g')),' '),
   sw.sw
  )) AS words,
  first_value(m.event_id) OVER (PARTITION BY m.meeting_date,m.parent_committee ORDER BY m.event_id ASC,m.title ASC)=
   first_value(m.event_id) OVER (PARTITION BY m.meeting_date,m.parent_committee ORDER BY m.event_id DESC,m.title ASC) AS single_event_on_date
 FROM raw_meeting_committees m
 CROSS JOIN stopwords sw
), senate_people AS (
 SELECT record_sha_hex,array_distinct(array_agg(family)) AS families
 FROM appearance_people
 WHERE source='senate_page' AND family IS NOT NULL AND NOT statement
 GROUP BY record_sha_hex
), meeting_known_people AS (
 SELECT event_id,array_distinct(array_agg(family)) AS families
 FROM (
  SELECT pml.event_id,ap.family
  FROM package_meeting_links pml
  JOIN appearance_people ap ON ap.source='mods' AND ap.package_id=pml.package_id
  WHERE pml.witness_eligible AND ap.family IS NOT NULL AND NOT ap.statement
  UNION ALL
  SELECT ap.event_id,ap.family
  FROM appearance_people ap
  WHERE ap.source='congress_gov' AND ap.event_id IS NOT NULL AND ap.family IS NOT NULL AND NOT ap.statement
 ) p
 GROUP BY event_id
), dated_candidates AS (
 SELECT
  s.record_sha_hex,
  s.source_url,
  s.banking_hearing_url,
  m.event_id,
  s.single_url_on_date,
  m.single_event_on_date,
  m.requires_overlap,
  coalesce(cast(cardinality(array_intersect(sp.families,mp.families)) AS BIGINT),cast(0 AS BIGINT)) AS shared_surnames,
  cast(cardinality(array_intersect(s.words,m.words)) AS BIGINT) AS shared_words
 FROM senate_pages s
 JOIN meeting_parent_committees m
  ON m.parent_committee=s.parent_committee AND m.meeting_date=s.page_date
 LEFT JOIN senate_people sp ON sp.record_sha_hex=s.record_sha_hex
 LEFT JOIN meeting_known_people mp ON mp.event_id=m.event_id
), dated_scored AS (
 SELECT
  record_sha_hex,
  source_url,
  banking_hearing_url,
  event_id,
  shared_surnames,
  shared_surnames*cast(100 AS BIGINT)+shared_words AS score
 FROM dated_candidates
 WHERE (single_event_on_date AND single_url_on_date AND NOT requires_overlap)
  OR shared_surnames>0
  OR shared_words>=2
), sha_ranked AS (
 SELECT
  record_sha_hex,
  source_url,
  banking_hearing_url,
  event_id,
  shared_surnames,
  score,
  row_number() OVER (PARTITION BY record_sha_hex ORDER BY score DESC,event_id ASC) AS sha_rn,
  lead(score) OVER (PARTITION BY record_sha_hex ORDER BY score DESC,event_id ASC) AS next_sha_score
 FROM dated_scored
), unique_sha_winners AS (
 SELECT record_sha_hex,source_url,banking_hearing_url,event_id,shared_surnames,score
 FROM sha_ranked
 WHERE sha_rn=1 AND (next_sha_score IS NULL OR next_sha_score<score)
), event_ranked AS (
 SELECT
  record_sha_hex,
  source_url,
  banking_hearing_url,
  event_id,
  shared_surnames,
  score,
  first_value(score) OVER (PARTITION BY event_id ORDER BY score DESC) AS max_event_score
 FROM unique_sha_winners
), event_top_winners AS (
 SELECT
  record_sha_hex,
  event_id,
  banking_hearing_url,
  first_value(source_url) OVER (PARTITION BY event_id ORDER BY source_url ASC,record_sha_hex ASC)=
   first_value(source_url) OVER (PARTITION BY event_id ORDER BY source_url DESC,record_sha_hex ASC)
   OR first_value(shared_surnames) OVER (PARTITION BY event_id ORDER BY shared_surnames DESC,record_sha_hex ASC)>0 AS keep_event
 FROM event_ranked
 WHERE score=max_event_score
)
SELECT record_sha_hex,event_id,banking_hearing_url
FROM event_top_winners
WHERE keep_event
