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
), markup_page_videos AS (
 SELECT DISTINCT k.video_key AS markup_video_key
 FROM (SELECT DISTINCT video_key FROM recording_page_video_events WHERE video_key IS NOT NULL) k
 JOIN videos_export v ON v.video_key=k.video_key
 WHERE v.title IS NOT NULL
  AND regexp_like(v.title,'(?i)\b(markup|organizational\s+meeting|subcommittee\s+assignments)\b')
), page_meeting_candidates AS (
 SELECT p.video_key,p.event_id,p.source_ref,
  lower(coalesce(m.meeting_type,''))='markup'
   OR regexp_like(coalesce(m.title,''),'(?i)\b(markup|business\s+meeting|organizational|subcommittee\s+assignments)\b') AS is_markup_meeting
 FROM recording_page_video_events p
 JOIN known_meetings m ON m.event_id=p.event_id
 WHERE p.video_key IS NOT NULL AND p.event_id IS NOT NULL
), page_rows AS (
 SELECT DISTINCT cast('event' AS VARCHAR) AS subject_kind,cast(pm.event_id AS VARCHAR) AS subject_id,
  pm.event_id,cast(NULL AS VARCHAR) AS package_id,pm.video_key,cast(NULL AS VARCHAR) AS url,
  cast('committee_page' AS VARCHAR) AS basis,cast('linked' AS VARCHAR) AS decision,cast(100 AS SMALLINT) AS score,
  cast('unknown' AS VARCHAR) AS recording_scope,cast('asserted' AS VARCHAR) AS status,
  cast(NULL AS VARCHAR) AS note,pm.source_ref
 FROM markup_page_videos mv
 RIGHT JOIN page_meeting_candidates pm ON mv.markup_video_key=pm.video_key
 WHERE mv.markup_video_key IS NULL OR pm.is_markup_meeting
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
