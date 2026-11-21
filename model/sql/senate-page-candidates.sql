-- Candidate (senate_page, meeting) pairs sharing parent committee and hearing date (ct-j2yo, ct-uul8).
-- Materialized once so both pre-package witness corroboration (senate_page_prelim_links) and
-- post-package witness resolution (senate_page_meeting_links) share one scan of captures and page_facts.
WITH stopwords AS (
 SELECT make_array(
  '','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that',
  'hearing','hearings','subcommittee','committee','senate','united','states','congress','washington','full','open','closed',
  'session','examine','examining','review','oversight','part','http','https','www','gov','html','htm','imo','media','doc','pdf','download','watch','live'
 ) AS sw
), capture_urls AS (
 SELECT DISTINCT sc.record_sha_hex,
  coalesce(c.url,c.requested_url,c.context_url) AS source_url,c.requested_url
 FROM senate_page_records sc
 JOIN captures c ON c.sha256=sc.sha256
 WHERE c.mode='fetch' AND c.complete AND c.outcome IN ('stored','unchanged')
  AND c.http_status BETWEEN 200 AND 299 AND c.sha256 IS NOT NULL
), pf_matched AS (
 SELECT sc.record_sha_hex,pf.heading,pf.title,pf.content_date,pf.text_head
 FROM senate_page_records sc
 JOIN page_facts pf ON pf.body_sha=sc.sha256
 WHERE pf.status='completed'
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
), page_addresses AS (
 SELECT DISTINCT record_sha_hex,address AS source_url,address=primary_url AS primary_address,
  url_resolve(address,cast(NULL AS VARCHAR)) AS parsed_url
 FROM (
  SELECT sc.record_sha_hex,coalesce(cu.source_url,sc.context_url) AS primary_url,
   unnest(make_array(coalesce(cu.source_url,sc.context_url),cu.requested_url)) AS address
  FROM capture_urls cu RIGHT JOIN senate_page_records sc ON cu.record_sha_hex=sc.record_sha_hex
 )
 WHERE address IS NOT NULL
), senate_pages_raw AS (
 SELECT
  a.record_sha_hex,
  -- The page key keeps nondefault ports; the hearing classifier uses only the path.
  regexp_replace(split_part(a.parsed_url,'#',1),'^https?://[^/:?#]+','') AS address_tail,
  (regexp_match(a.parsed_url,'^https?://[^/?#]+([^?#]*)'))[1] AS path,
  a.source_url,a.primary_address,sh.host,sh.parent_committee,
  coalesce(pf.heading,'')||' '||coalesce(pf.title,'')||' '||
   regexp_replace(a.source_url,'^https?://[^/]+/','') AS page_text,
  try_cast(pf.content_date AS DATE) AS pf_date,
  try_cast((regexp_match(coalesce(pf.title,''),'\[([0-9]{4}-[0-9]{2}-[0-9]{2})\]'))[1] AS DATE) AS title_bracket_date,
  try_cast((regexp_match(a.source_url,'/([0-9]{4}-[0-9]{2}-[0-9]{2})(?:[^0-9]|$)'))[1] AS DATE) AS url_iso_date,
  regexp_match(a.source_url,'/([0-9]{2})[/-]([0-9]{2})[/-]([0-9]{4})(?:[^0-9]|$)') AS url_mdy,
  regexp_match(a.source_url,'/([0-9]{2})-([0-9]{2})-([0-9]{2})-[a-zA-Z]') AS url_mdy2,
  coalesce(pf.text_head,'') AS text_head
 FROM senate_hosts sh
 JOIN (pf_matched pf RIGHT JOIN page_addresses a ON pf.record_sha_hex=a.record_sha_hex)
  ON sh.host=(regexp_match(a.parsed_url,'^https?://(?:www[.])?([a-z0-9-]+)[.]senate[.]gov(?:[:/?#]|$)'))[1]
), senate_text_dates AS (
 SELECT r.*,
  -- Compare within the mapped parent (ag/agriculture are one publisher). Keep the
  -- nondefault port, path case and query values. Banking's pager appends an empty field.
  parent_committee||rtrim(split_part(address_tail,'?',1),'/')||
   coalesce('?'||nullif(rtrim((regexp_match(address_tail,'^[^?]*[?](.*)$'))[1],'&'),''),'') AS page_key,
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
  FROM (
   SELECT *,CASE WHEN host='banking' AND path ILIKE '/hearings/%' THEN source_url END AS banking_hearing_url,
    host='banking' AND rtrim(path,'/') IN ('/hearings/witness-list','/witness-list') AS banking_directory
   FROM senate_pages_raw
  )
  -- A redirect's request can identify a directory. Only the primary address supplies meeting evidence.
  WHERE primary_address OR banking_directory
 ) r
), senate_pages_grouped AS (
 SELECT
  r.record_sha_hex,
  -- If one body came from unrelated paths, it can stand on its own but cannot
  -- make another body its mirror merely by choosing the first captured address.
  CASE WHEN min(r.page_key)=max(r.page_key) THEN min(r.page_key)
   ELSE 'body:'||r.record_sha_hex END AS page_key,
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
 -- A directory lists people across hearings. Any directory capture disqualifies
 -- the body for this committee, including captures at otherwise unrecognized aliases.
 HAVING NOT bool_or(r.banking_directory)
), senate_pages AS (
 SELECT
  g.record_sha_hex,
  g.page_key,
  g.banking_hearing_url,
  g.parent_committee,
  g.page_date,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(g.page_text),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|[0-9]+)\b',' ','g')),' '),
   sw.sw
  )) AS words,
  first_value(g.page_key) OVER (PARTITION BY g.page_date,g.parent_committee ORDER BY g.page_key ASC,g.record_sha_hex ASC)=
   first_value(g.page_key) OVER (PARTITION BY g.page_date,g.parent_committee ORDER BY g.page_key DESC,g.record_sha_hex ASC) AS single_page_on_date
 FROM stopwords sw
 CROSS JOIN senate_pages_grouped g
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
  -- Page tokens already exclude stopwords before the intersection.
  string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(m.title,'')),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|[0-9]+)\b',' ','g')),' ') AS words,
  first_value(m.event_id) OVER (PARTITION BY m.meeting_date,m.parent_committee ORDER BY m.event_id ASC,m.title ASC)=
   first_value(m.event_id) OVER (PARTITION BY m.meeting_date,m.parent_committee ORDER BY m.event_id DESC,m.title ASC) AS single_event_on_date
 FROM raw_meeting_committees m
), senate_people AS (
 SELECT record_sha_hex,array_distinct(array_agg(family)) AS families
 FROM appearance_people
 WHERE source='senate_page' AND family IS NOT NULL AND NOT statement
 GROUP BY record_sha_hex
)
SELECT
 s.record_sha_hex,
 s.page_key,
 s.banking_hearing_url,
 m.event_id,
 s.single_page_on_date,
 m.single_event_on_date,
 m.requires_overlap,
 cast(cardinality(array_intersect(s.words,m.words)) AS BIGINT) AS shared_words,
 sp.families
FROM senate_people sp
RIGHT JOIN (
 senate_pages s
 JOIN meeting_parent_committees m
  ON m.parent_committee=s.parent_committee AND m.meeting_date=s.page_date
) ON sp.record_sha_hex=s.record_sha_hex
