-- Link present Senate committee hearing pages (senate_page) to canonical meetings (ct-j2yo).
-- Pages resolve by parent committee (.senate.gov host) and hearing date (page_facts.content_date,
-- bracketed [YYYY-MM-DD] in title, URL date tokens, written Month DD, YYYY in text_head, or
-- witness document link dates), disambiguated across same-day committee meetings by witness
-- surname overlap (with MODS / Congress.gov) and substantive title/slug word overlap.
-- Undated committee pages resolve only when substantive title words agree uniquely with one meeting.
-- Empty or absent senate_page containers are excluded so they never suppress MODS witnesses.
WITH senate_candidates AS (
 SELECT DISTINCT r.record_sha_hex,
  arrow_cast(decode(r.record_sha_hex,'hex'),'FixedSizeBinary(32)') AS sha256
 FROM selected_appearance_records r
 WHERE r.source='senate_page' AND r.status='completed'
  AND coalesce(nullif(trim(r.collection_state),''),'present')='present'
  AND coalesce(array_length(r.appearances),0)>0
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
  substr(lower(system_code),1,4)||'00' AS parent_committee
 FROM spicy_committees
 WHERE parent_system_code IS NULL AND lower(system_code)<>'jjec00'
  AND regexp_like(coalesce(website_url,''),'(?i)^https?://(?:www[.])?[a-z0-9-]+[.]senate[.]gov')
 UNION
 SELECT 'aging' AS host,'sssp00' AS parent_committee
 UNION SELECT 'ag','ssaf00'
 UNION SELECT 'agriculture','ssaf00'
 UNION SELECT 'appropriations','ssap00'
 UNION SELECT 'armed-services','ssas00'
 UNION SELECT 'banking','ssbk00'
 UNION SELECT 'budget','ssbu00'
 UNION SELECT 'commerce','sscm00'
 UNION SELECT 'energy','sseg00'
 UNION SELECT 'epw','ssev00'
 UNION SELECT 'ethics','sset00'
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
 UNION SELECT 'jec','jcse00'
), senate_app_rows AS (
 SELECT r.record_sha_hex,unnest(r.appearances) AS a
 FROM selected_appearance_records r
 JOIN senate_candidates sc ON sc.record_sha_hex=r.record_sha_hex
 WHERE r.source='senate_page' AND r.appearances IS NOT NULL
), senate_doc_links AS (
 SELECT record_sha_hex,trim(unnest(a['document_links'])) AS link
 FROM senate_app_rows
 WHERE a['document_links'] IS NOT NULL
), doc_link_dates AS (
 SELECT record_sha_hex,
  min(try_cast((regexp_match(link,'([0-9]{4}-[0-9]{2}-[0-9]{2})'))[1] AS DATE)) AS link_date
 FROM senate_doc_links
 WHERE regexp_like(link,'[0-9]{4}-[0-9]{2}-[0-9]{2}')
 GROUP BY record_sha_hex
), senate_pages_raw AS (
 SELECT
  r.record_sha_hex,
  coalesce(cu.source_url,r.context_url) AS source_url,
  sh.parent_committee,
  coalesce(pf.heading,'')||' '||coalesce(pf.title,'')||' '||
   regexp_replace(coalesce(cu.source_url,r.context_url,''),'^https?://[^/]+/','') AS page_text,
  try_cast(pf.content_date AS DATE) AS pf_date,
  try_cast((regexp_match(coalesce(pf.title,''),'\[([0-9]{4}-[0-9]{2}-[0-9]{2})\]'))[1] AS DATE) AS title_bracket_date,
  try_cast((regexp_match(coalesce(cu.source_url,r.context_url,''),'/([0-9]{4}-[0-9]{2}-[0-9]{2})(?:[^0-9]|$)'))[1] AS DATE) AS url_iso_date,
  regexp_match(coalesce(cu.source_url,r.context_url,''),'/([0-9]{2})[/-]([0-9]{2})[/-]([0-9]{4})(?:[^0-9]|$)') AS url_mdy,
  regexp_match(coalesce(cu.source_url,r.context_url,''),'/([0-9]{2})-([0-9]{2})-([0-9]{2})-[a-zA-Z]') AS url_mdy2,
  regexp_match(coalesce(pf.text_head,''),'(?i)\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-9]{1,2}),\s*([0-9]{4})\b') AS th_mdy,
  dld.link_date
 FROM selected_appearance_records r
 JOIN senate_candidates sc ON sc.record_sha_hex=r.record_sha_hex
 LEFT JOIN capture_urls cu ON cu.record_sha_hex=r.record_sha_hex
 LEFT JOIN page_facts pf ON pf.body_sha=sc.sha256 AND pf.status='completed'
 LEFT JOIN doc_link_dates dld ON dld.record_sha_hex=r.record_sha_hex
 JOIN senate_hosts sh ON sh.host=lower((regexp_match(coalesce(cu.source_url,r.context_url,''),'(?i)^https?://(?:www[.])?([a-z0-9-]+)[.]senate[.]gov'))[1])
 WHERE r.source='senate_page'
), senate_pages AS (
 SELECT
  record_sha_hex,
  min(source_url) AS source_url,
  parent_committee,
  min(coalesce(
   pf_date,
   title_bracket_date,
   url_iso_date,
   CASE WHEN url_mdy IS NOT NULL THEN try_cast(url_mdy[3]||'-'||url_mdy[1]||'-'||url_mdy[2] AS DATE) END,
   CASE WHEN url_mdy2 IS NOT NULL THEN try_cast('20'||url_mdy2[3]||'-'||url_mdy2[1]||'-'||url_mdy2[2] AS DATE) END,
   CASE WHEN th_mdy IS NOT NULL THEN try_cast(
    th_mdy[3]||'-'||
    CASE lower(th_mdy[1])
     WHEN 'january' THEN '01' WHEN 'february' THEN '02' WHEN 'march' THEN '03'
     WHEN 'april' THEN '04' WHEN 'may' THEN '05' WHEN 'june' THEN '06'
     WHEN 'july' THEN '07' WHEN 'august' THEN '08' WHEN 'september' THEN '09'
     WHEN 'october' THEN '10' WHEN 'november' THEN '11' WHEN 'december' THEN '12'
    END||'-'||lpad(th_mdy[2],2,'0') AS DATE) END,
   link_date
  )) AS page_date,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(min(page_text)),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|[0-9]+)\b',' ','g')),' '),
   make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','senate','united','states','congress','washington','full','open','closed','session','examine','examining','review','oversight','part','http','https','www','gov','html','htm','imo','media','doc','pdf','download','watch','live')
  )) AS words
 FROM senate_pages_raw
 GROUP BY record_sha_hex,parent_committee
), meeting_parent_committees AS (
 SELECT DISTINCT
  m.event_id,
  m.meeting_date,
  substr(lower(c['system_code']),1,4)||'00' AS parent_committee,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(m.title,'')),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|[0-9]+)\b',' ','g')),' '),
   make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','senate','united','states','congress','washington','full','open','closed','session','examine','examining','review','oversight','part','http','https','www','gov','html','htm','imo','media','doc','pdf','download','watch','live')
  )) AS words
 FROM (
  SELECT event_id,meeting_date,title,unnest(committees) AS c
  FROM meetings_resolved
  WHERE chamber IN ('senate','joint') AND meeting_date IS NOT NULL
   AND NOT coalesce(not_held,false) AND committees IS NOT NULL
 ) m
 WHERE c['system_code'] IS NOT NULL AND trim(c['system_code'])<>''
 UNION
 SELECT DISTINCT
  m.event_id,
  m.meeting_date,
  substr(lower(m.committee_key),1,4)||'00' AS parent_committee,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(m.title,'')),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|[0-9]+)\b',' ','g')),' '),
   make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','senate','united','states','congress','washington','full','open','closed','session','examine','examining','review','oversight','part','http','https','www','gov','html','htm','imo','media','doc','pdf','download','watch','live')
  )) AS words
 FROM meetings_resolved m
 WHERE m.chamber IN ('senate','joint') AND m.meeting_date IS NOT NULL
  AND NOT coalesce(m.not_held,false)
  AND m.committee_key IS NOT NULL AND trim(m.committee_key)<>''
), date_committee_event_counts AS (
 SELECT parent_committee,meeting_date,count(DISTINCT event_id) AS n_events
 FROM meeting_parent_committees
 GROUP BY parent_committee,meeting_date
), date_committee_url_counts AS (
 SELECT parent_committee,page_date,count(DISTINCT source_url) AS n_urls
 FROM senate_pages
 WHERE page_date IS NOT NULL
 GROUP BY parent_committee,page_date
), senate_people AS (
 SELECT DISTINCT record_sha_hex,family
 FROM appearance_people
 WHERE source='senate_page' AND family IS NOT NULL AND NOT statement
), meeting_known_people AS (
 SELECT DISTINCT pml.event_id,ap.family
 FROM package_meeting_links pml
 JOIN appearance_people ap ON ap.source='mods' AND ap.package_id=pml.package_id
 WHERE ap.family IS NOT NULL AND NOT ap.statement
 UNION
 SELECT DISTINCT ap.event_id,ap.family
 FROM appearance_people ap
 WHERE ap.source='congress_gov' AND ap.event_id IS NOT NULL AND ap.family IS NOT NULL AND NOT ap.statement
), dated_candidates AS (
 SELECT
  s.record_sha_hex,
  s.source_url,
  s.parent_committee,
  s.page_date,
  m.event_id,
  ec.n_events,
  uc.n_urls,
  cardinality(array_intersect(s.words,m.words)) AS shared_words
 FROM senate_pages s
 JOIN meeting_parent_committees m
  ON m.parent_committee=s.parent_committee AND m.meeting_date=s.page_date
 JOIN date_committee_event_counts ec
  ON ec.parent_committee=s.parent_committee AND ec.meeting_date=s.page_date
 JOIN date_committee_url_counts uc
  ON uc.parent_committee=s.parent_committee AND uc.page_date=s.page_date
 WHERE s.page_date IS NOT NULL
), shared_surnames AS (
 SELECT dc.record_sha_hex,dc.event_id,count(DISTINCT sp.family) AS shared_surnames
 FROM (SELECT DISTINCT record_sha_hex,event_id FROM dated_candidates) dc
 JOIN senate_people sp ON sp.record_sha_hex=dc.record_sha_hex
 JOIN meeting_known_people mp ON mp.event_id=dc.event_id AND mp.family=sp.family
 GROUP BY dc.record_sha_hex,dc.event_id
), dated_scored AS (
 SELECT
  dc.record_sha_hex,
  dc.event_id,
  dc.n_events,
  dc.n_urls,
  coalesce(ss.shared_surnames,0) AS shared_surnames,
  dc.shared_words,
  coalesce(ss.shared_surnames,0)*100+dc.shared_words AS score
 FROM dated_candidates dc
 LEFT JOIN shared_surnames ss ON ss.record_sha_hex=dc.record_sha_hex AND ss.event_id=dc.event_id
 WHERE (dc.n_events=1 AND dc.n_urls=1)
  OR coalesce(ss.shared_surnames,0)>0
  OR dc.shared_words>0
), best_per_sha AS (
 SELECT record_sha_hex,max(score) AS max_score
 FROM dated_scored
 GROUP BY record_sha_hex
), sha_top_matches AS (
 SELECT ds.record_sha_hex,ds.event_id,ds.score
 FROM dated_scored ds
 JOIN best_per_sha b ON b.record_sha_hex=ds.record_sha_hex AND ds.score=b.max_score
), unique_sha_winners AS (
 SELECT record_sha_hex,min(event_id) AS event_id,min(score) AS score
 FROM sha_top_matches
 GROUP BY record_sha_hex
 HAVING count(DISTINCT event_id)=1
), best_per_event AS (
 SELECT event_id,max(score) AS max_score
 FROM unique_sha_winners
 GROUP BY event_id
), dated_links AS (
 SELECT u.record_sha_hex,u.event_id
 FROM unique_sha_winners u
 JOIN best_per_event be ON be.event_id=u.event_id AND u.score=be.max_score
), undated_candidates AS (
 SELECT
  s.record_sha_hex,
  m.event_id,
  cardinality(array_intersect(s.words,m.words)) AS shared_words
 FROM senate_pages s
 JOIN meeting_parent_committees m ON m.parent_committee=s.parent_committee
 WHERE s.page_date IS NULL
  AND cardinality(s.words)>=3 AND cardinality(m.words)>=3
  AND cardinality(array_intersect(s.words,m.words))>=3
  AND 2*cardinality(array_intersect(s.words,m.words))>=least(cardinality(s.words),cardinality(m.words))
), undated_best AS (
 SELECT record_sha_hex,max(shared_words) AS max_words
 FROM undated_candidates
 GROUP BY record_sha_hex
), undated_links AS (
 SELECT uc.record_sha_hex,min(uc.event_id) AS event_id
 FROM undated_candidates uc
 JOIN undated_best ub ON ub.record_sha_hex=uc.record_sha_hex AND uc.shared_words=ub.max_words
 GROUP BY uc.record_sha_hex
 HAVING count(DISTINCT uc.event_id)=1
)
SELECT record_sha_hex,event_id FROM dated_links
UNION
SELECT record_sha_hex,event_id FROM undated_links
