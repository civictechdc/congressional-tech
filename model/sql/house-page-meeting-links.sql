-- Link House committee proceeding pages holding recordings to canonical meetings (ct-ywz2, ct-414r).
-- Pages resolve either by a unique single-meeting proceeding document linked from the page
-- (HHRG/HMKP/HMTG or docs.house.gov/meetings/ address) or by parent committee (.house.gov host)
-- and proceeding date, corroborated by substantive title/heading/measure word overlap (or unique
-- same-kind proceeding when one side carries only a generic kind label).
-- Proceeding kind separates roundtables from markups and hearings; explicit House event IDs on the
-- page (page_facts.named_meetings or House repository/congress.gov EventID citations) veto date
-- links to a conflicting event_id; and trailing committee site-name suffixes are stripped from
-- page titles before overlap scoring. Each accepted row carries deterministic rule provenance
-- (link_rule and match_note with sorted shared words when present).
-- "One page on that date" counts pages, not addresses: a committee serves one page under its bare
-- host and its party host (science.house.gov, republicans-science.house.gov), and the queue fetching
-- the second address removed a correct match on 2026-11-17 (ct-mwod). page_key is host_stem (the
-- one place the host prefixes are stripped) with the address's path and query, so the same path and
-- query on those hosts is one page. The two party sites are different publishers, so a date
-- holding both a democrats- and a republicans- page is never one page (party_site). It cannot
-- see an alias whose path or query differs.
WITH stopwords AS (
 SELECT make_array(
  '','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that',
  'hearing','hearings','subcommittee','committee','house','united','states','congress','washington','full','open','closed','public',
  'session','examine','examining','review','oversight','part','http','https','www','gov','html','htm','aspx','events','event','calendar',
  'eventsingle','eventid','democrats','republicans','markups','markup','business','meeting','entitled','legislative','office'
 ) AS sw
), house_hosts AS (
 SELECT 'agriculture' AS host,'hsag00' AS parent_committee
 UNION ALL SELECT 'appropriations','hsap00'
 UNION ALL SELECT 'armedservices','hsas00'
 UNION ALL SELECT 'budget','hsbu00'
 UNION ALL SELECT 'cha','hsha00'
 UNION ALL SELECT 'china','hlzs00'
 UNION ALL SELECT 'climatecrisis','hlcn00'
 UNION ALL SELECT 'coronavirus','hlvc00'
 UNION ALL SELECT 'edworkforce','hsed00'
 UNION ALL SELECT 'education','hsed00'
 UNION ALL SELECT 'energycommerce','hsif00'
 UNION ALL SELECT 'ethics','hsso00'
 UNION ALL SELECT 'financialservices','hsba00'
 UNION ALL SELECT 'foreignaffairs','hsfa00'
 UNION ALL SELECT 'homeland','hshm00'
 UNION ALL SELECT 'intelligence','hlig00'
 UNION ALL SELECT 'january6th','hlij00'
 UNION ALL SELECT 'judiciary','hsju00'
 UNION ALL SELECT 'modernization','hlmh00'
 UNION ALL SELECT 'naturalresources','hsii00'
 UNION ALL SELECT 'oversight','hsgo00'
 UNION ALL SELECT 'rules','hsru00'
 UNION ALL SELECT 'science','hssy00'
 UNION ALL SELECT 'smallbusiness','hssm00'
 UNION ALL SELECT 'transportation','hspw00'
 UNION ALL SELECT 'veterans','hsvr00'
 UNION ALL SELECT 'waysandmeans','hswm00'
), page_urls AS (
 SELECT rps.page_body,sa.url AS source_url
 FROM recording_page_sources rps
 JOIN source_addresses sa ON sa.source_id=rps.source_id
 WHERE sa.url IS NOT NULL
 GROUP BY rps.page_body,sa.url
), page_doc_links AS (
 SELECT vp.page_body,pl.source_id
 FROM recording_video_pages vp
 JOIN publisher_links pl ON pl.page_body=vp.page_body
 WHERE pl.source_id IS NOT NULL
), page_doc_events AS (
 SELECT pdl.page_body,try_cast(cml.meeting_keys[1] AS BIGINT) AS event_id
 FROM page_doc_links pdl
 JOIN document_members dm ON dm.source_id=pdl.source_id
 JOIN component_meeting_links cml ON cml.component=dm.component
 WHERE cardinality(cml.meeting_keys)=1
  AND try_cast(cml.meeting_keys[1] AS BIGINT) IS NOT NULL
  AND (regexp_like(coalesce(dm.filename,''),'(?i)^(?:hhrg|hmkp|hmtg)-')
   OR regexp_like(coalesce(dm.source_url,''),'(?i)docs[.]house[.]gov/meetings/'))
), unique_doc_events AS (
 SELECT page_body,min(event_id) AS event_id,
  cast('house_doc_link' AS VARCHAR) AS link_rule,
  cast('house_doc_link' AS VARCHAR) AS match_note
 FROM page_doc_events
 GROUP BY page_body
 HAVING min(event_id)=max(event_id)
), page_facts_matched AS (
 SELECT vp.page_body,pf.title,pf.heading,pf.content_date,pf.text_head,pf.named_meetings
 FROM recording_video_pages vp
 JOIN page_facts pf ON pf.body_sha=vp.body_sha
 WHERE pf.status='completed'
), pages_raw AS (
 SELECT
  u.page_body,
  u.source_url,
  u.host_stem||lower(regexp_replace(u.source_url,'^https?://[^/]+','')) AS page_key,
  u.party_site,
  hh.parent_committee,
  coalesce(pf.heading,'')||' '||
   regexp_replace(
    regexp_replace(
     regexp_replace(coalesce(pf.title,''),'(?i)\s*\|\s*[^|]*\bcommittee\b[^|]*$',''),
     '(?i)\s*[-–—]\s*(?:hearings?|markups?|events?|press\s+releases?)\s*[-–—]\s*(?:u\.?s\.?\s+)?(?:the\s+)?(?:house\s+)?committee.*$',''
    ),
    '(?i)\s*[-–—]\s*(?:u\.?s\.?\s+)?(?:the\s+)?(?:house\s+)?committee\s+on\s+.*$',''
   )||' '||regexp_replace(u.source_url,'^https?://[^/]+/','') AS title_text,
  coalesce(pf.heading,'')||' '||coalesce(pf.title,'')||' '||coalesce(pf.text_head,'')||' '||
   CASE WHEN regexp_like(u.source_url,'(?i)(?:docs[.]house[.]gov/|congress[.]gov/event/)') THEN u.source_url ELSE '' END AS event_citation_text,
  coalesce(pf.text_head,'') AS text_head,
  try_cast(pf.content_date AS DATE) AS pf_date,
  array_distinct(array_concat(
   coalesce(pf.named_meetings,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')),
   CASE
    WHEN try_cast((regexp_match(coalesce(pf.heading,'')||' '||coalesce(pf.title,''),'(?i)(?:docs[.]house[.]gov/[^\s"''<>]*[?&]eventid=|congress[.]gov/event/[0-9]+/house-event/|\bevent\s*id\s*[=:#]\s*)(1[0-9]{5})\b'))[1] AS BIGINT) IS NOT NULL
    THEN make_array(try_cast((regexp_match(coalesce(pf.heading,'')||' '||coalesce(pf.title,''),'(?i)(?:docs[.]house[.]gov/[^\s"''<>]*[?&]eventid=|congress[.]gov/event/[0-9]+/house-event/|\bevent\s*id\s*[=:#]\s*)(1[0-9]{5})\b'))[1] AS BIGINT))
    ELSE arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')
   END,
   CASE
    WHEN try_cast((regexp_match(coalesce(pf.text_head,''),'(?i)(?:docs[.]house[.]gov/[^\s"''<>]*[?&]eventid=|congress[.]gov/event/[0-9]+/house-event/|\bevent\s*id\s*[=:#]\s*)(1[0-9]{5})\b'))[1] AS BIGINT) IS NOT NULL
    THEN make_array(try_cast((regexp_match(coalesce(pf.text_head,''),'(?i)(?:docs[.]house[.]gov/[^\s"''<>]*[?&]eventid=|congress[.]gov/event/[0-9]+/house-event/|\bevent\s*id\s*[=:#]\s*)(1[0-9]{5})\b'))[1] AS BIGINT))
    ELSE arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')
   END,
   CASE
    WHEN try_cast((regexp_match(u.source_url,'(?i)(?:docs[.]house[.]gov/[^\s"''<>]*[?&]eventid=|congress[.]gov/event/[0-9]+/house-event/)(1[0-9]{5})\b'))[1] AS BIGINT) IS NOT NULL
    THEN make_array(try_cast((regexp_match(u.source_url,'(?i)(?:docs[.]house[.]gov/[^\s"''<>]*[?&]eventid=|congress[.]gov/event/[0-9]+/house-event/)(1[0-9]{5})\b'))[1] AS BIGINT))
    ELSE arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')
   END
  )) AS row_stated_ids,
  regexp_match(u.source_url,'/([0-9]{2})/([0-9]{2})/([0-9]{4})(?:/|$)') AS u_mdy_slash,
  regexp_match(u.source_url,'(?:^|[^0-9])([0-9]{1,2})[.-]([0-9]{1,2})[.-](20[0-9]{2})(?:[^0-9]|$)') AS u_mdy_dot4,
  regexp_match(u.source_url,'(?:^|-)([0-9]{2})([0-9]{2})(20[0-9]{2})(?:[^0-9]|$)') AS u_mdy8,
  regexp_match(u.source_url,'(?:^|-)([0-9])([0-9]{2})(20[0-9]{2})(?:[^0-9]|$)') AS u_mdy7
 FROM page_facts_matched pf
 RIGHT JOIN (
  SELECT h.page_body,h.source_url,
   regexp_replace(h.host,'^(?:edit-)?(?:democrats-|republicans-|archives[0-9]*-)','') AS host_stem,
   (regexp_match(h.host,'^(?:edit-)?(democrats|republicans)-'))[1] AS party_site
  FROM (
   SELECT pu.page_body,pu.source_url,
    lower((regexp_match(pu.source_url,'(?i)^https?://(?:www[.])?([a-z0-9-]+)[.]house[.]gov'))[1]) AS host
   FROM page_urls pu
  ) h
 ) u ON pf.page_body=u.page_body
 JOIN house_hosts hh ON hh.host=u.host_stem
), pages_text_dates AS (
 SELECT r.*,
  CASE WHEN t_full IS NOT NULL THEN try_cast(t_full[3]||'-'||lpad(cast(array_position(full_m,lower(t_full[1])) AS VARCHAR),2,'0')||'-'||lpad(t_full[2],2,'0') AS DATE) END AS text_full_date,
  CASE WHEN t_abbr IS NOT NULL THEN try_cast(t_abbr[3]||'-'||lpad(cast(array_position(abbr_m,substr(lower(t_abbr[1]),1,3)) AS VARCHAR),2,'0')||'-'||lpad(t_abbr[2],2,'0') AS DATE) END AS text_abbr_date,
  CASE WHEN t_slash4 IS NOT NULL THEN try_cast(t_slash4[3]||'-'||lpad(t_slash4[1],2,'0')||'-'||lpad(t_slash4[2],2,'0') AS DATE) END AS text_slash_date,
  CASE WHEN t_dot2 IS NOT NULL THEN try_cast('20'||t_dot2[3]||'-'||t_dot2[1]||'-'||t_dot2[2] AS DATE) END AS text_dot2_date
 FROM (
  SELECT *,
   make_array('january','february','march','april','may','june','july','august','september','october','november','december') AS full_m,
   make_array('jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec') AS abbr_m,
   regexp_match(text_head,'(?i)\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-9]{1,2}),?\s+(20[0-9]{2})\b') AS t_full,
   regexp_match(text_head,'(?i)\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[.]?\s+([0-9]{1,2}),?\s+(20[0-9]{2})\b') AS t_abbr,
   regexp_match(text_head,'\b([0-9]{1,2})/([0-9]{1,2})/(20[0-9]{2})\b') AS t_slash4,
   regexp_match(text_head,'\b([0-9]{2})[.]([0-9]{2})[.]([0-9]{2})\b') AS t_dot2
  FROM pages_raw
 ) r
), pages_grouped AS (
 SELECT
  page_body,
  parent_committee,
  min(page_key) AS page_key,
  min(party_site) AS party_lo,
  max(party_site) AS party_hi,
  min(title_text) AS title_text,
  min(title_text||' '||text_head) AS full_text,
  min(event_citation_text) AS event_citation_text,
  array_sort(array_distinct(flatten(array_agg(row_stated_ids)))) AS stated_event_ids,
  coalesce(
   min(pf_date),
   min(text_full_date),
   min(text_abbr_date),
   min(text_slash_date),
   min(text_dot2_date),
   min(CASE WHEN u_mdy_slash IS NOT NULL THEN try_cast(u_mdy_slash[3]||'-'||u_mdy_slash[1]||'-'||u_mdy_slash[2] AS DATE) END),
   min(CASE WHEN u_mdy_dot4 IS NOT NULL THEN try_cast(u_mdy_dot4[3]||'-'||lpad(u_mdy_dot4[1],2,'0')||'-'||lpad(u_mdy_dot4[2],2,'0') AS DATE) END),
   min(CASE WHEN u_mdy8 IS NOT NULL THEN try_cast(u_mdy8[3]||'-'||u_mdy8[1]||'-'||u_mdy8[2] AS DATE) END),
   min(CASE WHEN u_mdy7 IS NOT NULL THEN try_cast(u_mdy7[3]||'-0'||u_mdy7[1]||'-'||u_mdy7[2] AS DATE) END)
  ) AS page_date
 FROM pages_text_dates
 GROUP BY page_body,parent_committee
), house_pages AS (
 SELECT
  g.page_body,
  g.parent_committee,
  g.page_date,
  g.stated_event_ids,
  g.event_citation_text,
  regexp_like(g.title_text,'(?i)\broundtable\b') AS is_roundtable,
  regexp_like(g.title_text,'(?i)\b(markup|business\s+meeting)\b') AS is_markup,
  CASE
   WHEN regexp_like(g.title_text,'(?i)\broundtable\b') THEN 'roundtable'
   WHEN regexp_like(g.title_text,'(?i)\b(markup|business\s+meeting)\b') THEN 'markup'
   ELSE 'hearing'
  END AS proceeding_kind,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(g.title_text),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),
   sw.sw
  )) AS title_words,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(g.full_text),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),
   sw.sw
  )) AS full_words,
  min(g.page_key) OVER (PARTITION BY g.page_date,g.parent_committee)=
   max(g.page_key) OVER (PARTITION BY g.page_date,g.parent_committee)
   AND coalesce(min(g.party_lo) OVER (PARTITION BY g.page_date,g.parent_committee)=
    max(g.party_hi) OVER (PARTITION BY g.page_date,g.parent_committee),true) AS single_page_on_date
 FROM pages_grouped g
 CROSS JOIN stopwords sw
 WHERE g.page_date IS NOT NULL
), raw_house_meetings AS (
 SELECT DISTINCT
  m.event_id,
  m.meeting_date,
  coalesce(m.title,'') AS title,
  coalesce(m.title,'')||' '||coalesce(array_to_string(m.subject_keys,' '),'') AS title_and_subjects,
  coalesce(m.not_held,false) AS not_held,
  regexp_like(coalesce(m.title,''),'(?i)\broundtable\b') AS is_roundtable,
  lower(coalesce(m.meeting_type,''))='markup' OR regexp_like(coalesce(m.title,''),'(?i)\b(markup|business\s+meeting)\b') AS is_markup,
  CASE
   WHEN regexp_like(coalesce(m.title,''),'(?i)\broundtable\b') THEN 'roundtable'
   WHEN lower(coalesce(m.meeting_type,''))='markup' OR regexp_like(coalesce(m.title,''),'(?i)\b(markup|business\s+meeting)\b') THEN 'markup'
   ELSE 'hearing'
  END AS proceeding_kind,
  substr(lower(c['system_code']),1,4)||'00' AS parent_committee
 FROM (
  SELECT event_id,meeting_date,meeting_type,title,subject_keys,not_held,unnest(committees) AS c
  FROM meetings_resolved
  WHERE chamber='house' AND meeting_date IS NOT NULL AND committees IS NOT NULL
 ) m
 WHERE c['system_code'] IS NOT NULL AND trim(c['system_code'])<>''
), house_meetings AS (
 SELECT
  m.event_id,
  m.meeting_date,
  m.parent_committee,
  m.not_held,
  m.is_roundtable,
  m.is_markup,
  m.proceeding_kind,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(m.title_and_subjects),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),
   sw.sw
  )) AS words,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(m.title),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),
   sw.sw
  )) AS title_only_words,
  first_value(m.event_id) OVER (PARTITION BY m.meeting_date,m.parent_committee,m.proceeding_kind ORDER BY m.event_id ASC,m.title ASC)=
   first_value(m.event_id) OVER (PARTITION BY m.meeting_date,m.parent_committee,m.proceeding_kind ORDER BY m.event_id DESC,m.title ASC) AS single_kind_on_date
 FROM raw_house_meetings m
 CROSS JOIN stopwords sw
), dated_overlaps AS (
 SELECT
  p.page_body,
  m.event_id,
  p.single_page_on_date,
  m.single_kind_on_date,
  p.proceeding_kind=m.proceeding_kind AS same_kind,
  p.is_roundtable<>m.is_roundtable AS roundtable_mismatch,
  coalesce(cardinality(p.stated_event_ids),0)>0
   AND NOT array_has(p.stated_event_ids,m.event_id)
   AND NOT regexp_like(p.event_citation_text,'(?i)(?:docs[.]house[.]gov/[^\s"''<>]*[?&]eventid=|congress[.]gov/event/[0-9]+/house-event/|\bevent\s*id\s*[=:#]\s*)'||cast(m.event_id AS VARCHAR)||'\b') AS stated_event_conflict,
  NOT m.not_held AS held_ok,
  cardinality(p.title_words)=0 OR cardinality(m.title_only_words)=0 AS generic_side,
  cast(cardinality(m.title_only_words) AS BIGINT) AS meeting_title_word_count,
  array_sort(array_intersect(p.title_words,m.words)) AS title_overlap_words,
  array_sort(array_intersect(p.full_words,m.words)) AS full_overlap_words
 FROM house_pages p
 JOIN house_meetings m ON m.parent_committee=p.parent_committee AND m.meeting_date=p.page_date
), dated_candidates AS (
 SELECT
  page_body,
  event_id,
  single_page_on_date,
  single_kind_on_date,
  same_kind,
  roundtable_mismatch,
  stated_event_conflict,
  held_ok,
  generic_side,
  meeting_title_word_count,
  title_overlap_words,
  full_overlap_words,
  cast(cardinality(title_overlap_words) AS BIGINT) AS shared_title_words,
  cast(cardinality(full_overlap_words) AS BIGINT) AS shared_full_words
 FROM dated_overlaps
), dated_scored AS (
 SELECT
  page_body,
  event_id,
  shared_title_words*cast(20 AS BIGINT)+shared_full_words*cast(5 AS BIGINT)
   +(CASE WHEN same_kind THEN cast(4 AS BIGINT) ELSE cast(0 AS BIGINT) END)
   +(CASE WHEN held_ok THEN cast(1 AS BIGINT) ELSE cast(0 AS BIGINT) END) AS score,
  CASE
   WHEN shared_title_words>=2 THEN cast('house_title_words' AS VARCHAR)
   WHEN shared_title_words=1 AND shared_full_words>=2 AND same_kind THEN cast('house_title_and_full_words' AS VARCHAR)
   WHEN shared_title_words=0 AND same_kind AND shared_full_words>=3
    AND (shared_full_words>=4 OR shared_full_words*cast(2 AS BIGINT)>=meeting_title_word_count)
    THEN cast('house_text_head_strong' AS VARCHAR)
   WHEN shared_title_words=0 AND same_kind AND shared_full_words>=2 THEN cast('house_text_head_weak' AS VARCHAR)
   WHEN single_kind_on_date AND single_page_on_date AND same_kind AND shared_title_words>=1 THEN cast('house_single_day_title' AS VARCHAR)
   ELSE cast('house_single_day_generic' AS VARCHAR)
  END AS link_rule,
  CASE
   WHEN shared_title_words>=2 THEN 'house_title_words: '||array_to_string(title_overlap_words,', ')
   WHEN shared_title_words=1 AND shared_full_words>=2 AND same_kind THEN 'house_title_and_full_words: '||array_to_string(full_overlap_words,', ')
   WHEN shared_title_words=0 AND same_kind AND shared_full_words>=3
    AND (shared_full_words>=4 OR shared_full_words*cast(2 AS BIGINT)>=meeting_title_word_count)
    THEN 'house_text_head_strong: '||array_to_string(full_overlap_words,', ')
   WHEN shared_title_words=0 AND same_kind AND shared_full_words>=2 THEN 'house_text_head_weak: '||array_to_string(full_overlap_words,', ')
   WHEN single_kind_on_date AND single_page_on_date AND same_kind AND shared_title_words>=1 THEN 'house_single_day_title: '||array_to_string(title_overlap_words,', ')
   WHEN shared_full_words>0 THEN 'house_single_day_generic: '||array_to_string(full_overlap_words,', ')
   ELSE cast('house_single_day_generic' AS VARCHAR)
  END AS match_note
 FROM dated_candidates
 WHERE NOT roundtable_mismatch
  AND NOT stated_event_conflict
  AND (
   shared_title_words>=2
   OR (shared_full_words>=2 AND same_kind)
   OR (single_kind_on_date AND single_page_on_date AND same_kind AND (shared_title_words>=1 OR generic_side))
  )
), dated_ranked AS (
 SELECT
  page_body,
  event_id,
  score,
  link_rule,
  match_note,
  row_number() OVER (PARTITION BY page_body ORDER BY score DESC,event_id ASC) AS rn,
  lead(score) OVER (PARTITION BY page_body ORDER BY score DESC,event_id ASC) AS next_score
 FROM dated_scored
), dated_winners AS (
 SELECT page_body,event_id,link_rule,match_note
 FROM dated_ranked
 WHERE rn=1 AND (next_score IS NULL OR next_score<score)
), all_candidates AS (
 SELECT page_body,event_id,link_rule,match_note,0 AS priority FROM unique_doc_events
 UNION ALL
 SELECT page_body,event_id,link_rule,match_note,1 AS priority FROM dated_winners
), chosen AS (
 SELECT page_body,event_id,link_rule,match_note,
  row_number() OVER (PARTITION BY page_body ORDER BY priority ASC,event_id ASC) AS rn
 FROM all_candidates
)
SELECT page_body,event_id,link_rule,match_note
FROM chosen
WHERE rn=1
