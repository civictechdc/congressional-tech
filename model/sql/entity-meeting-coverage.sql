WITH package_meetings AS (
 SELECT package_id,min(event_id) AS event_id FROM meeting_transcript_links GROUP BY package_id HAVING count(DISTINCT event_id)=1
), recording_evidence AS (
 SELECT event_id,coalesce(video_key,url) AS ref FROM recording_matches_export
 WHERE event_id IS NOT NULL AND (status IN ('asserted','claimed') OR (status='decided' AND recording_scope<>'unknown'))
 UNION ALL
 SELECT p.event_id,coalesce(m.video_key,m.url) FROM recording_matches_export m JOIN package_meetings p ON m.package_id=p.package_id
 WHERE m.status='decided' AND m.recording_scope<>'unknown'
), recording_present AS (
 SELECT event_id,count(DISTINCT ref) AS n FROM recording_evidence GROUP BY event_id
), recording_absent AS (
 -- Absence is only ever a curated verdict on a package tied to exactly one meeting; zero rows prove nothing.
 SELECT DISTINCT p.event_id FROM recording_matches_export m JOIN package_meetings p ON m.package_id=p.package_id
 WHERE m.basis='curated' AND m.status='decided' AND m.decision='no_video_found'
), recording_rows AS (
 SELECT e.event_id,'recording' AS aspect,
  CASE WHEN p.n IS NOT NULL THEN 'present' WHEN a.event_id IS NOT NULL THEN 'confirmed_absent' ELSE 'unknown' END AS state,
  CASE WHEN p.n IS NOT NULL THEN 'recording_matches' WHEN a.event_id IS NOT NULL THEN 'curated' ELSE 'none' END AS basis,
  cast(coalesce(p.n,0) AS INT) AS count
 FROM meetings_export e LEFT JOIN recording_present p ON e.event_id=p.event_id LEFT JOIN recording_absent a ON e.event_id=a.event_id
), transcript_rows AS (
 SELECT e.event_id,'transcript' AS aspect,
  CASE WHEN coalesce(array_length(e.transcripts),0)>0 THEN 'present'
       WHEN coalesce(array_length(r.transcript_jackets),0)>0 THEN 'unresolved' ELSE 'not_stated' END AS state,
  'meetings.transcripts' AS basis,cast(coalesce(array_length(e.transcripts),0) AS INT) AS count
 FROM meetings_export e LEFT JOIN meetings_resolved r ON e.event_id=r.event_id
), document_counts AS (
 SELECT event_id,count(*) AS n FROM (SELECT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered WHERE meeting_keys IS NOT NULL) GROUP BY event_id
), document_rows AS (
 SELECT e.event_id,'documents' AS aspect,CASE WHEN d.n IS NOT NULL THEN 'present' ELSE 'not_stated' END AS state,
  'list.meeting_keys' AS basis,cast(coalesce(d.n,0) AS INT) AS count
 FROM meetings_export e LEFT JOIN document_counts d ON e.event_id=d.event_id
), witness_counts AS (
 SELECT event_id,count(*) AS n FROM witnesses_export WHERE event_id IS NOT NULL AND name IS NOT NULL GROUP BY event_id
), witness_states AS (
 SELECT event_id,max(CASE WHEN collection_state='unresolved' THEN 2 WHEN collection_state='empty' THEN 1 ELSE 0 END) AS rank
 FROM (
  SELECT event_id,CASE WHEN status<>'completed' OR collection_state IN ('failed','unrecognized') THEN 'unresolved'
    ELSE coalesce(nullif(trim(collection_state),''),CASE WHEN coalesce(array_length(appearances),0)>0 THEN 'present' ELSE 'empty' END) END AS collection_state
  FROM appearance_records_input r
  WHERE NOT EXISTS (SELECT 1 FROM parser_versions WHERE parser LIKE 'appearance_records.%')
   OR EXISTS (SELECT 1 FROM parser_versions v WHERE v.parser='appearance_records.'||r.source AND v.version=r.parser_version)
 ) WHERE event_id IS NOT NULL GROUP BY event_id
), witness_rows AS (
 SELECT e.event_id,'witnesses' AS aspect,
  CASE WHEN c.n IS NOT NULL THEN 'present' WHEN s.rank=2 THEN 'unresolved' WHEN s.rank=1 THEN 'empty' ELSE 'not_stated' END AS state,
  'appearance_records' AS basis,cast(coalesce(c.n,0) AS INT) AS count
 FROM meetings_export e LEFT JOIN witness_counts c ON e.event_id=c.event_id LEFT JOIN witness_states s ON e.event_id=s.event_id
), caption_counts AS (
 SELECT m.event_id,sum(CASE WHEN v.has_caption THEN 1 ELSE 0 END) AS yes,sum(CASE WHEN v.has_caption=false THEN 1 ELSE 0 END) AS no
 FROM (SELECT DISTINCT event_id,video_key FROM recording_matches_export WHERE event_id IS NOT NULL AND video_key IS NOT NULL) m
 JOIN videos_export v ON m.video_key=v.video_key GROUP BY m.event_id
), caption_rows AS (
 SELECT e.event_id,'captions' AS aspect,
  CASE WHEN c.yes>0 THEN 'present' WHEN c.no>0 THEN 'empty' WHEN c.event_id IS NOT NULL THEN 'unknown' ELSE 'not_stated' END AS state,
  'videos.has_caption' AS basis,cast(coalesce(c.yes,0) AS INT) AS count
 FROM meetings_export e LEFT JOIN caption_counts c ON e.event_id=c.event_id
)
SELECT event_id,aspect,state,basis,count,cast(NULL AS VARCHAR) AS reason FROM recording_rows
UNION ALL SELECT event_id,aspect,state,basis,count,cast(NULL AS VARCHAR) FROM transcript_rows
UNION ALL SELECT event_id,aspect,state,basis,count,cast(NULL AS VARCHAR) FROM document_rows
UNION ALL SELECT event_id,aspect,state,basis,count,cast(NULL AS VARCHAR) FROM witness_rows
UNION ALL SELECT event_id,aspect,state,basis,count,cast(NULL AS VARCHAR) FROM caption_rows
