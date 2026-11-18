WITH sw AS (
 SELECT make_array(
  '','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that',
  'hearing','subcommittee','committee','house','senate','united','state','congres','congressional','washington',
  'full','open','closed','public','session','examine','examining','examination','review','reviewing','oversight','part',
  'http','www','gov','html','htm','aspx','event','calendar','eventsingle','eventid','democrat','democratic','republican',
  'markup','busines','meeting','entitled','titled','legislative','legislation','office','virtual','hybrid','remote','joint','select','special',
  'field','live','stream','livestream','video','webcast','archived','archive','member','day','pending','variou','measure','bill','one','draft','discussion',
  'act','title','code','amend','purpose','other','certain','relating','provide','direct','secretary','department','agency','administration','federal','national',
  'american','america','fiscal','year','budget','request','prioritie','priority','perspective','stakeholder','update','statu','future','current'
 ) AS words,
 make_array('january','february','march','april','may','june','july','august','september','october','november','december') AS full_m,
 make_array('jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec') AS abbr_m
), publisher AS (
 SELECT event_id,unnest(videos) AS v FROM meetings_resolved
), publisher_rows AS (
 SELECT DISTINCT cast('event' AS VARCHAR) AS subject_kind,cast(p.event_id AS VARCHAR) AS subject_id,
  p.event_id,cast(NULL AS VARCHAR) AS package_id,
  coalesce(a.canonical_key,p.v['video_key']) AS video_key,p.v['url'] AS url,
  cast('publisher_link' AS VARCHAR) AS basis,cast('linked' AS VARCHAR) AS decision,cast(100 AS SMALLINT) AS score,
  cast('unknown' AS VARCHAR) AS recording_scope,cast('asserted' AS VARCHAR) AS status,
  cast(NULL AS VARCHAR) AS note,cast('meetings.videos' AS VARCHAR) AS source_ref
 FROM video_key_aliases a
 RIGHT JOIN publisher p ON a.alias_key=p.v['video_key']
), held_stated_video_events AS (
 SELECT pv.video_key,array_agg(DISTINCT hm.event_id) AS held_event_ids
 FROM (
  SELECT k.video_key,unnest(v.stated_event_ids) AS stated_id
  FROM (SELECT DISTINCT video_key FROM recording_page_video_events WHERE video_key IS NOT NULL) k
  JOIN videos_export v ON v.video_key=k.video_key
  WHERE coalesce(cardinality(v.stated_event_ids),0)>0
 ) pv
 JOIN (SELECT event_id FROM known_meetings WHERE NOT coalesce(not_held,false)) hm ON hm.event_id=pv.stated_id
 GROUP BY pv.video_key
), page_video_raw AS (
 SELECT kv.video_key,kv.title,kv.source_description,kv.duration_seconds,kv.system_code,
  cast(kv.published_at AS DATE) AS pub_date,kv.stated_event_ids,hs.held_event_ids,
  sw.words AS swwords,sw.full_m,sw.abbr_m,
  regexp_match(coalesce(kv.title,''),'\b(20[0-3][0-9]-[0-9]{2}-[0-9]{2})\b') AS v_iso,
  regexp_match(coalesce(kv.title,''),'\b([0-9]{1,2})[/.-]([0-9]{1,2})[/.-](20[0-3][0-9])\b') AS v_mdy,
  regexp_match(coalesce(kv.title,''),'\b([01][0-9])\s+([0-3][0-9])\s+(20[0-3][0-9])\b') AS v_spc,
  regexp_match(coalesce(kv.title,''),'\b(20[0-3][0-9])([01][0-9])([0-3][0-9])\b') AS v_ymd8,
  regexp_match(coalesce(kv.title,''),'^\s*([01][0-9])([0-3][0-9])([0-3][0-9])\b') AS v_mdy6,
  regexp_match(coalesce(kv.title,''),'(?i)\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-9]{1,2}),?\s+(20[0-3][0-9])\b') AS v_full,
  regexp_match(coalesce(kv.title,''),'(?i)\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[.]?\s+([0-9]{1,2}),?\s+(20[0-3][0-9])\b') AS v_abbr
 FROM held_stated_video_events hs
 RIGHT JOIN (
  SELECT k.video_key,v.title,v.source_description,v.duration_seconds,v.system_code,v.published_at,v.stated_event_ids
  FROM (SELECT DISTINCT video_key FROM recording_page_video_events WHERE video_key IS NOT NULL) k
  JOIN videos_export v ON v.video_key=k.video_key
 ) kv ON hs.video_key=kv.video_key
 CROSS JOIN sw
), page_video_facts AS (
 SELECT video_key,pub_date,stated_event_ids,held_event_ids,
  CASE WHEN system_code IS NOT NULL AND trim(system_code)<>'' THEN
   (CASE WHEN substr(lower(trim(system_code)),1,4)='jsec' THEN 'jjec' ELSE substr(lower(trim(system_code)),1,4) END)
  END AS v_parent,
  coalesce(
   CASE WHEN v_iso IS NOT NULL THEN try_cast(v_iso[1] AS DATE) END,
   CASE WHEN v_mdy IS NOT NULL THEN try_cast(v_mdy[3]||'-'||lpad(v_mdy[1],2,'0')||'-'||lpad(v_mdy[2],2,'0') AS DATE) END,
   CASE WHEN v_spc IS NOT NULL THEN try_cast(v_spc[3]||'-'||v_spc[1]||'-'||v_spc[2] AS DATE) END,
   CASE WHEN v_ymd8 IS NOT NULL THEN try_cast(v_ymd8[1]||'-'||v_ymd8[2]||'-'||v_ymd8[3] AS DATE) END,
   CASE WHEN v_mdy6 IS NOT NULL THEN try_cast('20'||v_mdy6[3]||'-'||v_mdy6[1]||'-'||v_mdy6[2] AS DATE) END,
   CASE WHEN v_full IS NOT NULL THEN try_cast(v_full[3]||'-'||lpad(cast(array_position(full_m,lower(v_full[1])) AS VARCHAR),2,'0')||'-'||lpad(v_full[2],2,'0') AS DATE) END,
   CASE WHEN v_abbr IS NOT NULL THEN try_cast(v_abbr[3]||'-'||lpad(cast(array_position(abbr_m,substr(lower(v_abbr[1]),1,3)) AS VARCHAR),2,'0')||'-'||lpad(v_abbr[2],2,'0') AS DATE) END
  ) AS v_date,
  title IS NOT NULL AND regexp_like(title,'(?i)\b(markup|organizational\s+meeting|subcommittee\s+assignments)\b') AS is_markup_video,
  title IS NOT NULL AND regexp_like(title,'(?i)\broundtable\b') AND NOT regexp_like(title,'(?i)\bhearing\b') AS is_roundtable_video,
  regexp_like(coalesce(title,''),'(?i)^\s*(?:[0-9./-]+\s*[-:]?\s*)?(?:(?:subcommittee\s+on\s+[a-z0-9 ,&''-]+|[a-z0-9 ,&''-]+\s+(?:subcommittee|committee)|full\s+committee)\s*)?(?:[-|–—:]\s*)?(?:(?:public|open|legislative|oversight|field|joint|virtual|hybrid|remote)\s+)*(?:hearing|markup|meeting|live\s*stream|webcast)(?:\s*:\s*pending\s+legislation)?(?:\s+[0-9./:-]+\s*(?:am|pm)?)?\s*$') AS is_generic_label,
  coalesce(duration_seconds,0)>=900
   AND NOT regexp_like(coalesce(title,''),'(?i)^\s*(?:[0-9./-]+\s*[-:]?\s*)?(?:(?:subcommittee\s+on\s+[a-z0-9 ,&''-]+|[a-z0-9 ,&''-]+\s+(?:subcommittee|committee)|full\s+committee)\s*)?(?:[-|–—:]\s*)?(?:(?:public|open|legislative|oversight|field|joint|virtual|hybrid|remote)\s+)*(?:hearing|markup|meeting|live\s*stream|webcast)(?:\s*:\s*pending\s+legislation)?(?:\s+[0-9./:-]+\s*(?:am|pm)?)?\s*$')
   AND NOT regexp_like(coalesce(title,''),'(?i):\s*pending\s+legislation\s*$')
   AND regexp_like(coalesce(title,''),'(?i)(?:[:“"”]|\b(?:hearing|roundtable|forum|briefing)\s+(?:on|to|re|into|examining|reviewing|assessing)\b)') AS has_explicit_topic,
  regexp_like(coalesce(title,''),'(?i)(?:\bsubcommittee\b|\bo\s*&\s*i\b)') AS says_subcommittee,
  regexp_like(coalesce(title,''),'(?i)(?:\bfull\s+(?:committee|cmte)\b|\bbefore\s+the\s+(?:house|senate)\s+(?:committee\s+on\s+)?[a-z &''-]+\s+committee\b)')
   AND NOT regexp_like(coalesce(title,''),'(?i)\bsubcommittee\b') AS says_full_committee,
  (regexp_match(regexp_replace(coalesce(title,''),'\b(?:HEARING|MARKUP|FULL|OPEN|PUBLIC|HYBRID|REMOTE|SELECT|JOINT|HOUSE|SENATE|PART|SUB|AND|THE|FOR|WITH|FROM)\b',' ','g'),'\b([A-Z]{3,6})\b'))[1] AS v_acronym,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|(?:fy)?20[0-9]{2}|fy[0-9]{2})\b',' ','g'),'\b([a-z0-9]{3,})s\b','$1','g')),' '),
   swwords
  )) AS v_words,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(title,'')||' '||coalesce(source_description,'')),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|(?:fy)?20[0-9]{2}|fy[0-9]{2})\b',' ','g'),'\b([a-z0-9]{3,})s\b','$1','g')),' '),
   swwords
  )) AS vd_words
 FROM page_video_raw
), page_meeting_committees AS (
 SELECT event_id,
  array_distinct(array_agg(CASE WHEN substr(code,1,4)='jsec' THEN 'jjec' ELSE substr(code,1,4) END)) AS parent_codes,
  bool_or(regexp_like(code,'00$')) AS has_full,
  bool_or(NOT regexp_like(code,'00$')) AS has_sub,
  bool_or(substr(code,1,2) IN ('hl','ht','sl','sc','sp','jc','jj','js')) AS has_select
 FROM (
  SELECT p.event_id,lower(trim(c['system_code'])) AS code
  FROM (SELECT DISTINCT event_id FROM recording_page_video_events WHERE event_id IS NOT NULL) p
  JOIN (SELECT event_id,unnest(committees) AS c FROM known_meetings WHERE NOT coalesce(not_held,false) AND committees IS NOT NULL) mc ON mc.event_id=p.event_id
  WHERE c['system_code'] IS NOT NULL AND trim(c['system_code'])<>''
 )
 GROUP BY event_id
), page_meeting_raw AS (
 SELECT m.event_id,m.meeting_date,m.meeting_type,m.title,m.subject_keys,
  mc.parent_codes,coalesce(mc.has_full,false) AS has_full,coalesce(mc.has_sub,false) AS has_sub,coalesce(mc.has_select,false) AS has_select,
  sw.words AS swwords,sw.full_m,sw.abbr_m,
  regexp_match(coalesce(m.title,''),'\b(20[0-3][0-9]-[0-9]{2}-[0-9]{2})\b') AS m_iso,
  regexp_match(coalesce(m.title,''),'\b([0-9]{1,2})[/.-]([0-9]{1,2})[/.-](20[0-3][0-9])\b') AS m_mdy,
  regexp_match(coalesce(m.title,''),'(?i)\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-9]{1,2}),?\s+(20[0-3][0-9])\b') AS m_full,
  regexp_match(coalesce(m.title,''),'(?i)\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[.]?\s+([0-9]{1,2}),?\s+(20[0-3][0-9])\b') AS m_abbr
 FROM page_meeting_committees mc
 RIGHT JOIN (
  SELECT m.event_id,m.meeting_date,m.meeting_type,m.title,m.subject_keys
  FROM (SELECT DISTINCT event_id FROM recording_page_video_events WHERE event_id IS NOT NULL) p
  JOIN known_meetings m ON m.event_id=p.event_id
  WHERE NOT coalesce(m.not_held,false)
 ) m ON mc.event_id=m.event_id
 CROSS JOIN sw
), page_meeting_facts AS (
 SELECT event_id,meeting_date,parent_codes,has_full,has_sub,has_select,
  lower(coalesce(meeting_type,''))='markup'
   OR regexp_like(coalesce(title,''),'(?i)\b(markup|business\s+meeting|organizational|subcommittee\s+assignments)\b') AS is_markup_meeting,
  regexp_like(coalesce(meeting_type,'')||' '||coalesce(title,''),'(?i)\broundtable\b') AS is_roundtable_meeting,
  regexp_like(coalesce(title,''),'(?i)\bfield\s+hearing\b') AS is_field_hearing,
  coalesce(
   CASE WHEN m_iso IS NOT NULL THEN try_cast(m_iso[1] AS DATE) END,
   CASE WHEN m_mdy IS NOT NULL THEN try_cast(m_mdy[3]||'-'||lpad(m_mdy[1],2,'0')||'-'||lpad(m_mdy[2],2,'0') AS DATE) END,
   CASE WHEN m_full IS NOT NULL THEN try_cast(m_full[3]||'-'||lpad(cast(array_position(full_m,lower(m_full[1])) AS VARCHAR),2,'0')||'-'||lpad(m_full[2],2,'0') AS DATE) END,
   CASE WHEN m_abbr IS NOT NULL THEN try_cast(m_abbr[3]||'-'||lpad(cast(array_position(abbr_m,substr(lower(m_abbr[1]),1,3)) AS VARCHAR),2,'0')||'-'||lpad(m_abbr[2],2,'0') AS DATE) END
  ) AS m_title_date,
  regexp_replace(regexp_replace(lower(regexp_replace(coalesce(title,''),'(?i)\b(?:the|and|for|with|from|into|over|under|upon|to|in|on|at|by|a|an|of)\b',' ','g')),'\b([a-z])[a-z]*\s*','$1','g'),'[^a-z]','','g')
   ||' '||regexp_replace(regexp_replace(lower(regexp_replace(coalesce(title,''),'(?i)\b(?:the|and|for|with|from|into|over|under|upon|to|in|on|at|by|a|an)\b',' ','g')),'\b([a-z])[a-z]*\s*','$1','g'),'[^a-z]','','g') AS m_initials,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|(?:fy)?20[0-9]{2}|fy[0-9]{2}|(?:hr|hres|hjres|hconres|s|sres|sjres|sconres)?[0-9]+)\b',' ','g'),'\b([a-z0-9]{3,})s\b','$1','g')),' '),
   swwords
  )) AS m_title_words,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(title,'')||' '||coalesce(array_to_string(subject_keys,' '),'')),'[^a-z0-9]+',' ','g'),'\b(?:[a-z0-9]{1,2}|(?:fy)?20[0-9]{2}|fy[0-9]{2})\b',' ','g'),'\b([a-z0-9]{3,})s\b','$1','g')),' '),
   swwords
  )) AS m_words
 FROM page_meeting_raw
), page_candidates AS (
 SELECT pm.video_key,pm.event_id,pm.source_ref,
  vf.video_key IS NOT NULL AS has_video,
  vf.is_markup_video,vf.is_roundtable_video,vf.pub_date,vf.v_date,vf.v_parent,
  vf.is_generic_label,vf.has_explicit_topic,vf.says_subcommittee,vf.says_full_committee,vf.v_acronym,
  cardinality(vf.v_words) AS v_word_n,
  cardinality(array_intersect(vf.v_words,pm.m_words)) AS shared_v_words,
  cardinality(array_intersect(vf.vd_words,pm.m_words)) AS shared_vd_words,
  CASE WHEN vf.stated_event_ids IS NOT NULL THEN coalesce(array_has(vf.stated_event_ids,pm.event_id),false) ELSE false END AS states_this_event,
  CASE WHEN vf.held_event_ids IS NOT NULL THEN cardinality(array_except(vf.held_event_ids,make_array(pm.event_id)))>0 ELSE false END AS states_other_held_event,
  pm.meeting_date,pm.parent_codes,pm.has_full,pm.has_sub,pm.has_select,
  pm.is_markup_meeting,pm.is_roundtable_meeting,pm.is_field_hearing,pm.m_title_date,pm.m_initials,
  cardinality(pm.m_title_words) AS m_title_word_n
 FROM page_video_facts vf
 RIGHT JOIN (
  SELECT p.video_key,p.event_id,p.source_ref,
   mf.meeting_date,mf.parent_codes,mf.has_full,mf.has_sub,mf.has_select,
   mf.is_markup_meeting,mf.is_roundtable_meeting,mf.is_field_hearing,mf.m_title_date,mf.m_initials,
   mf.m_words,mf.m_title_words
  FROM page_meeting_facts mf
  JOIN (SELECT video_key,event_id,source_ref FROM recording_page_video_events WHERE video_key IS NOT NULL AND event_id IS NOT NULL) p ON p.event_id=mf.event_id
 ) pm ON vf.video_key=pm.video_key
), page_rows AS (
 -- Reject committee-page embeds whose own hearing identity (date, committee, event ID, kind, or title)
 -- contradicts the held hearing they would attach to (ct-9vwc).
 SELECT DISTINCT cast('event' AS VARCHAR) AS subject_kind,cast(event_id AS VARCHAR) AS subject_id,
  event_id,cast(NULL AS VARCHAR) AS package_id,video_key,cast(NULL AS VARCHAR) AS url,
  cast('committee_page' AS VARCHAR) AS basis,cast('linked' AS VARCHAR) AS decision,cast(100 AS SMALLINT) AS score,
  cast('unknown' AS VARCHAR) AS recording_scope,cast('asserted' AS VARCHAR) AS status,
  cast(NULL AS VARCHAR) AS note,source_ref
 FROM page_candidates
 WHERE NOT has_video OR (
  (NOT is_markup_video OR is_markup_meeting)
  AND (NOT is_roundtable_video OR is_roundtable_meeting)
  AND (pub_date IS NULL OR meeting_date IS NULL OR pub_date>=meeting_date-INTERVAL '30' DAY OR states_this_event)
  AND (v_date IS NULL OR meeting_date IS NULL OR v_date=meeting_date
   OR (m_title_date IS NOT NULL AND v_date=m_title_date)
   OR states_this_event
   OR (shared_v_words>=2 AND NOT states_other_held_event
    AND ((v_date>=meeting_date-INTERVAL '14' DAY AND v_date<=meeting_date+INTERVAL '14' DAY)
     OR substr(cast(v_date AS VARCHAR),6,5)=substr(cast(meeting_date AS VARCHAR),6,5))))
  AND NOT (states_other_held_event AND NOT states_this_event
   AND (NOT is_generic_label OR (v_date IS NOT NULL AND meeting_date IS NOT NULL AND v_date<>meeting_date))
   AND shared_v_words<2)
  AND (v_parent IS NULL OR parent_codes IS NULL OR array_has(parent_codes,v_parent) OR has_select OR states_this_event OR shared_v_words>=2)
  AND (states_this_event OR parent_codes IS NULL OR has_select OR shared_vd_words>=2
   OR NOT ((has_full AND NOT has_sub AND NOT is_field_hearing AND says_subcommittee)
    OR (has_sub AND NOT has_full AND says_full_committee)))
  AND (states_this_event OR NOT has_explicit_topic OR v_word_n<2 OR m_title_word_n<2 OR shared_vd_words>0
   OR (v_acronym IS NOT NULL AND strpos(m_initials,lower(v_acronym))>0))
 )
), stated AS (
 SELECT video_key,encode(record_sha,'hex') AS record_hex,unnest(stated_event_ids) AS stated_id FROM videos_export
), stated_rows AS (
 -- A video's own text is a claim: committees mistag. A number no meeting has stays visible.
 SELECT cast('event' AS VARCHAR) AS subject_kind,cast(s.stated_id AS VARCHAR) AS subject_id,
  m.event_id,cast(NULL AS VARCHAR) AS package_id,s.video_key,cast(NULL AS VARCHAR) AS url,
  cast('video_states_event_id' AS VARCHAR) AS basis,cast('linked' AS VARCHAR) AS decision,
  CASE WHEN m.event_id IS NOT NULL THEN cast(95 AS SMALLINT) END AS score,
  cast('unknown' AS VARCHAR) AS recording_scope,cast('claimed' AS VARCHAR) AS status,
  CASE WHEN m.event_id IS NULL THEN concat('stated event id ',cast(s.stated_id AS VARCHAR),' has no meeting') END AS note,
  concat('video_records:',s.record_hex) AS source_ref
 FROM known_meetings m RIGHT JOIN stated s ON m.event_id=s.stated_id
), linked_packages AS (
 SELECT DISTINCT l.package_id FROM meeting_transcript_links l
 JOIN (SELECT event_id FROM publisher_rows UNION SELECT event_id FROM page_rows) p ON p.event_id=l.event_id
), refs AS (
 SELECT id,subject_kind,subject_id,verdict,note,disputed_by,unnest(video_refs) AS ref
 FROM active_recording_decisions WHERE array_length(video_refs)>0
 UNION ALL
 SELECT id,subject_kind,subject_id,verdict,note,disputed_by,cast(NULL AS VARCHAR) AS ref
 FROM active_recording_decisions WHERE coalesce(array_length(video_refs),0)=0
), curated_rows AS (
 SELECT r.subject_kind,r.subject_id,
  CASE WHEN r.subject_kind='event' THEN try_cast(r.subject_id AS BIGINT) END AS event_id,
  CASE WHEN r.subject_kind='package' THEN r.subject_id END AS package_id,
  CASE WHEN r.ref IS NOT NULL AND NOT regexp_like(r.ref,'^https?://') THEN concat('youtube:',r.ref) END AS video_key,
  CASE WHEN regexp_like(r.ref,'^https?://') THEN r.ref END AS url,
  cast('curated' AS VARCHAR) AS basis,r.verdict AS decision,cast(NULL AS SMALLINT) AS score,
  CASE WHEN r.verdict='partial_only' THEN 'excerpt' WHEN r.verdict LIKE 'found%' THEN 'full' ELSE 'unknown' END AS recording_scope,
  -- A negative verdict against a publisher's link is a conflict to show, not to settle.
  -- Old evidence against a negative verdict leaves it open until the native matcher decides.
  CASE WHEN r.verdict IN ('no_video_found','not_public') AND p.package_id IS NOT NULL THEN 'conflicting'
       WHEN r.disputed_by IS NOT NULL THEN 'unresolved' ELSE 'decided' END AS status,
  CASE WHEN r.disputed_by IS NOT NULL THEN concat_ws(' | ',r.note,concat('disputed by ',r.disputed_by)) ELSE r.note END AS note,concat('recording_decisions:',r.id) AS source_ref
 FROM refs r LEFT JOIN linked_packages p ON r.subject_kind='package' AND r.subject_id=p.package_id
), all_rows AS (
 SELECT * FROM publisher_rows UNION ALL SELECT * FROM page_rows UNION ALL SELECT * FROM stated_rows UNION ALL SELECT * FROM curated_rows
), keyed AS (
 SELECT *,encode(sha256(json_array(subject_kind,subject_id,coalesce(video_key,url,''),basis)),'hex') AS match_id FROM all_rows
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY match_id ORDER BY source_ref,url) AS rn FROM keyed
), package_links AS (
 -- The printed hearing can cover several sittings. Its agreement with a meeting
 -- establishes related package evidence, independent of which sitting a locator covers.
 SELECT package_id,array_agg(named_struct(
  'event_id',event_id,
  'basis',arrow_cast('print_agreement','Dictionary(Int32, Utf8)'),
  'scope',arrow_cast('package_context','Dictionary(Int32, Utf8)')
 ) ORDER BY event_id) AS meeting_links
 FROM package_meeting_links GROUP BY package_id
)
SELECT r.match_id,r.subject_kind,r.subject_id,r.event_id,r.package_id,r.video_key,r.url,r.basis,
 r.decision,r.score,r.recording_scope,r.status,r.note,r.source_ref,
 CASE WHEN e.event_id IS NOT NULL THEN make_array(named_struct(
  'event_id',e.event_id,
  'basis',arrow_cast('direct_event','Dictionary(Int32, Utf8)'),
  'scope',arrow_cast('event','Dictionary(Int32, Utf8)')
 ))
 ELSE coalesce(p.meeting_links,array_slice(make_array(named_struct(
  'event_id',cast(NULL AS BIGINT),
  'basis',arrow_cast(NULL,'Dictionary(Int32, Utf8)'),
  'scope',arrow_cast(NULL,'Dictionary(Int32, Utf8)')
 )),1,0)) END AS meeting_links
FROM package_links p
RIGHT JOIN (
 known_meetings e
 RIGHT JOIN ranked r ON r.event_id=e.event_id
) ON r.package_id=p.package_id
WHERE r.rn=1
