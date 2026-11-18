WITH publisher AS (
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
), page_stopwords AS (
 SELECT make_array(
  '','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that',
  'hearing','hearings','subcommittee','committee','house','united','states','congress','washington','full','open','closed','public',
  'session','examine','examining','review','oversight','part','http','https','www','gov','html','htm','aspx','events','event','calendar',
  'eventsingle','eventid','democrats','republicans','markups','markup','business','meeting','entitled','legislative','office'
 ) AS sw
), page_video_info AS (
 SELECT DISTINCT
  v.video_key,
  coalesce(v.stated_event_ids,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')) AS stated_event_ids,
  v.title IS NOT NULL AND regexp_like(v.title,'(?i)\b(markup|organizational\s+meeting|subcommittee\s+assignments)\b') AS is_markup_video,
  v.title IS NOT NULL AND regexp_like(v.title,'(?i)\broundtable\b') AS is_roundtable_video,
  v.title IS NOT NULL AND regexp_like(v.title,'(?i)\b(hearing|markup)\b') AS is_hearing_or_markup_video,
  v.title IS NOT NULL AND regexp_like(v.title,'(?i)(?:\bevent\s*id|\bid)\s*[=:#]\s*[0-9]{5,6}\b') AS has_explicit_event_id_in_title,
  v.title IS NULL
   OR cardinality(array_distinct(array_except(
       string_to_array(trim(regexp_replace(regexp_replace(lower(v.title),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),
       sw.sw
      )))=0
   OR regexp_like(trim(v.title),'(?i)^(?:(?:oversight|legislative|public|full\s+committee|subcommittee|joint|budget|democratic|republican|virtual|hybrid|live)\s+)*(?:(?:hearing|markup|mark-?up|business\s+meeting)\s*(?:\||[-–—:])\s*)?(?:(?:the\s+)?(?:select\s+)?subcommittee\s+on\s+[^:|]+|[^:|]+\s+subcommittee|full\s+committee)(?:\s*(?:oversight|legislative|public|joint|budget|business)?\s*(?:hearing|markup|mark-?up|meeting))?(?:\s*[-–—:,]?\s*(?:eventid\s*=\s*[0-9]+|[0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[.]?\s+[0-9]{1,2},?\s+[0-9]{4}))*\s*:?$')
   OR cardinality(array_distinct(array_except(
       string_to_array(trim(regexp_replace(regexp_replace(
        regexp_replace(lower(v.title),'(?i)\b(?:[0-9]{1,2}[./:-][0-9]{1,2}[./:-][0-9]{2,4}|[0-9]{1,2}:[0-9]{2}\s*(?:am|pm)|eventid\s*=\s*[0-9]+|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[.]?\s+[0-9]{1,2},?\s+[0-9]{4}|part\s+[0-9]+|full\s+committee|subcommittee|joint|field|virtual|hybrid|oversight|legislative|public|democratic|republican|business|meeting|markup|mark-?up|hearing|hearings|pending\s+legislation|various\s+measures|live)\b',' ','g'),
        '[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),
       sw.sw
      )))=0 AS is_generic_video_title,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(v.title,'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),
   sw.sw
  )) AS video_words
 FROM (SELECT DISTINCT video_key FROM recording_page_video_events WHERE video_key IS NOT NULL) k
 JOIN videos_export v ON v.video_key=k.video_key
 CROSS JOIN page_stopwords sw
), page_video_stated_overlaps AS (
 SELECT
  s.video_key,
  max(CASE WHEN m.event_id IS NOT NULL THEN cast(1 AS BIGINT) ELSE cast(0 AS BIGINT) END)=1 AS has_known_stated_meeting,
  max(coalesce(cast(cardinality(array_intersect(
   s.video_words,
   array_distinct(array_except(
    string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(m.title,'')||' '||coalesce(array_to_string(m.subject_keys,' '),'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),
    sw.sw
   ))
  )) AS BIGINT),cast(0 AS BIGINT))) AS max_stated_overlap
 FROM (
  SELECT video_key,video_words,unnest(stated_event_ids) AS stated_id
  FROM page_video_info
  WHERE cardinality(stated_event_ids)>0
 ) s
 LEFT JOIN known_meetings m ON m.event_id=s.stated_id
 CROSS JOIN page_stopwords sw
 GROUP BY s.video_key
), page_meeting_candidates AS (
 SELECT p.video_key,p.event_id,p.source_ref,p.link_rule,p.match_note,
  lower(coalesce(m.meeting_type,''))='markup'
   OR regexp_like(coalesce(m.title,''),'(?i)\b(markup|business\s+meeting|organizational|subcommittee\s+assignments)\b') AS is_markup_meeting,
  regexp_like(coalesce(m.title,''),'(?i)\broundtable\b') AS is_roundtable_meeting,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(m.title,'')||' '||coalesce(array_to_string(m.subject_keys,' '),'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),
   sw.sw
  )) AS meeting_words
 FROM recording_page_video_events p
 JOIN known_meetings m ON m.event_id=p.event_id
 CROSS JOIN page_stopwords sw
 WHERE p.video_key IS NOT NULL AND p.event_id IS NOT NULL
), page_evaluated AS (
 SELECT pm.event_id,pm.video_key,pm.source_ref,pm.link_rule,pm.match_note,
  pm.is_markup_meeting,pm.is_roundtable_meeting,
  coalesce(pv.is_markup_video,false) AS is_markup_video,
  coalesce(pv.is_roundtable_video,false) AS is_roundtable_video,
  coalesce(pv.is_hearing_or_markup_video,false) AS is_hearing_or_markup_video,
  coalesce(pv.has_explicit_event_id_in_title,false) AS has_explicit_event_id_in_title,
  coalesce(pv.is_generic_video_title,true) AS is_generic_video_title,
  coalesce(pv.stated_event_ids,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')) AS stated_event_ids,
  coalesce(sv.has_known_stated_meeting,false) AS has_known_stated_meeting,
  coalesce(sv.max_stated_overlap,cast(0 AS BIGINT)) AS max_stated_overlap,
  cast(cardinality(array_intersect(
   coalesce(pv.video_words,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')),
   pm.meeting_words
  )) AS BIGINT) AS video_meeting_overlap
 FROM page_video_stated_overlaps sv
 RIGHT JOIN (
  page_video_info pv
  RIGHT JOIN page_meeting_candidates pm ON pv.video_key=pm.video_key
 ) ON sv.video_key=pm.video_key
), page_rows AS (
 SELECT DISTINCT cast('event' AS VARCHAR) AS subject_kind,cast(e.event_id AS VARCHAR) AS subject_id,
  e.event_id,cast(NULL AS VARCHAR) AS package_id,e.video_key,cast(NULL AS VARCHAR) AS url,
  cast('committee_page' AS VARCHAR) AS basis,cast('linked' AS VARCHAR) AS decision,cast(100 AS SMALLINT) AS score,
  cast('unknown' AS VARCHAR) AS recording_scope,cast('asserted' AS VARCHAR) AS status,
  e.match_note AS note,e.source_ref
 FROM page_evaluated e
 WHERE (NOT e.is_markup_video OR e.is_markup_meeting)
  AND NOT (e.is_roundtable_video AND NOT e.is_roundtable_meeting)
  AND NOT (e.is_roundtable_meeting AND e.is_hearing_or_markup_video AND NOT e.is_roundtable_video)
  AND NOT (
   cardinality(e.stated_event_ids)>0
   AND NOT array_has(e.stated_event_ids,e.event_id)
   AND (
    (NOT e.is_generic_video_title AND (
     (e.video_meeting_overlap=0 AND e.max_stated_overlap>=2)
     OR (e.video_meeting_overlap<=1 AND e.max_stated_overlap>=4)
    ))
    OR (e.link_rule IN ('house_title_words','house_title_and_full_words','house_text_head_strong','house_text_head_weak','house_single_day_title','house_single_day_generic')
     AND e.video_meeting_overlap=0
     AND (
      (NOT e.is_generic_video_title AND e.has_explicit_event_id_in_title)
      OR (e.has_known_stated_meeting AND e.max_stated_overlap>0)
     ))
   )
  )
  AND NOT (
   e.link_rule='house_text_head_weak'
   AND NOT e.is_generic_video_title
   AND e.video_meeting_overlap=0
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
