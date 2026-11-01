WITH publisher AS (
 SELECT event_id,unnest(videos) AS v FROM meetings_resolved
), publisher_rows AS (
 SELECT DISTINCT cast('event' AS VARCHAR) AS subject_kind,cast(event_id AS VARCHAR) AS subject_id,
  event_id,cast(NULL AS VARCHAR) AS package_id,v['video_key'] AS video_key,v['url'] AS url,
  cast('publisher_link' AS VARCHAR) AS basis,cast('linked' AS VARCHAR) AS decision,cast(100 AS SMALLINT) AS score,
  cast('unknown' AS VARCHAR) AS recording_scope,cast('asserted' AS VARCHAR) AS status,
  cast(NULL AS VARCHAR) AS note,cast('meetings.videos' AS VARCHAR) AS source_ref
 FROM publisher
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
 FROM stated s LEFT JOIN meetings_export m ON m.event_id=s.stated_id
), linked_packages AS (
 SELECT DISTINCT l.package_id FROM meeting_transcript_links l JOIN publisher_rows p ON p.event_id=l.event_id
), refs AS (
 SELECT id,subject_kind,subject_id,verdict,note,unnest(video_refs) AS ref
 FROM active_recording_decisions WHERE array_length(video_refs)>0
 UNION ALL
 SELECT id,subject_kind,subject_id,verdict,note,cast(NULL AS VARCHAR) AS ref
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
  CASE WHEN r.verdict IN ('no_video_found','not_public') AND p.package_id IS NOT NULL THEN 'conflicting' ELSE 'decided' END AS status,
  r.note,concat('recording_decisions:',r.id) AS source_ref
 FROM refs r LEFT JOIN linked_packages p ON r.subject_kind='package' AND r.subject_id=p.package_id
), all_rows AS (
 SELECT * FROM publisher_rows UNION ALL SELECT * FROM stated_rows UNION ALL SELECT * FROM curated_rows
), keyed AS (
 SELECT *,encode(sha256(json_array(subject_kind,subject_id,coalesce(video_key,url,''),basis)),'hex') AS match_id FROM all_rows
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY match_id ORDER BY source_ref,url) AS rn FROM keyed
)
SELECT match_id,subject_kind,event_id,package_id,video_key,url,basis,decision,score,recording_scope,status,note,source_ref
FROM ranked WHERE rn=1
