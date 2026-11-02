WITH package_meetings AS (
 SELECT package_id,min(event_id) AS event_id FROM meeting_transcript_links GROUP BY package_id HAVING count(DISTINCT event_id)=1
), recording_links AS (
 -- A video reaches a meeting through the meeting itself or a package tied to that meeting alone.
 SELECT m.event_id,m.basis,m.status,m.decision,m.recording_scope,m.video_key,coalesce(m.video_key,m.url) AS ref FROM recording_matches_export m WHERE m.event_id IS NOT NULL
 UNION ALL
 SELECT p.event_id,m.basis,m.status,m.decision,m.recording_scope,m.video_key,coalesce(m.video_key,m.url) FROM recording_matches_export m JOIN package_meetings p ON m.package_id=p.package_id
), recording_levels AS (
 SELECT event_id,
  count(DISTINCT CASE WHEN status='asserted' OR (status='decided' AND recording_scope='full') THEN ref END) AS full_n,
  count(DISTINCT CASE WHEN status='decided' AND recording_scope='excerpt' THEN ref END) AS excerpt_n,
  count(DISTINCT CASE WHEN status='claimed' THEN ref END) AS claimed_n,
  sum(CASE WHEN basis='curated' AND decision='not_public' THEN 1 ELSE 0 END) AS not_public_n
 FROM recording_links GROUP BY event_id
), recording_absent AS (
 -- Absence is only ever curated: an undisputed negative verdict on every package of the meeting,
 -- each tied to this meeting alone. A sibling package with no verdict leaves it open; zero rows prove nothing.
 SELECT p.event_id FROM package_meetings p
 JOIN (SELECT DISTINCT package_id FROM recording_matches_export
  WHERE basis='curated' AND status='decided' AND decision='no_video_found') n ON n.package_id=p.package_id
 GROUP BY p.event_id
 HAVING count(*)=(SELECT count(DISTINCT l.package_id) FROM meeting_transcript_links l WHERE l.event_id=p.event_id)
), recording_disputed AS (
 SELECT DISTINCT p.event_id FROM recording_matches_export m JOIN package_meetings p ON m.package_id=p.package_id
 WHERE m.basis='curated' AND m.status='unresolved'
), recording_rows AS (
 SELECT e.event_id,'recording' AS aspect,
  CASE WHEN l.full_n>0 THEN 'present' WHEN l.excerpt_n>0 THEN 'partial' WHEN l.claimed_n>0 THEN 'claimed'
       WHEN d.event_id IS NOT NULL THEN 'unresolved' WHEN l.not_public_n>0 THEN 'not_public'
       WHEN a.event_id IS NOT NULL THEN 'confirmed_absent' ELSE 'unknown' END AS state,
  CASE WHEN l.full_n>0 OR l.excerpt_n>0 OR l.claimed_n>0 THEN 'recording_matches'
       WHEN d.event_id IS NOT NULL OR l.not_public_n>0 OR a.event_id IS NOT NULL THEN 'curated' ELSE 'none' END AS basis,
  cast(coalesce(l.full_n,0)+coalesce(l.excerpt_n,0)+coalesce(l.claimed_n,0) AS INT) AS count
 FROM meetings_export e LEFT JOIN recording_levels l ON e.event_id=l.event_id LEFT JOIN recording_absent a ON e.event_id=a.event_id
  LEFT JOIN recording_disputed d ON e.event_id=d.event_id
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
  FROM selected_appearance_records r
 ) WHERE event_id IS NOT NULL GROUP BY event_id
), witness_rows AS (
 SELECT e.event_id,'witnesses' AS aspect,
  CASE WHEN c.n IS NOT NULL THEN 'present' WHEN s.rank=2 THEN 'unresolved' WHEN s.rank=1 THEN 'empty' ELSE 'not_stated' END AS state,
  'appearance_records' AS basis,cast(coalesce(c.n,0) AS INT) AS count
 FROM meetings_export e LEFT JOIN witness_counts c ON e.event_id=c.event_id LEFT JOIN witness_states s ON e.event_id=s.event_id
), linked_videos AS (
 SELECT DISTINCT event_id,video_key FROM recording_links WHERE video_key IS NOT NULL
), caption_counts AS (
 -- An observation is a retained track or YouTube's own flag. has_caption=false misses
 -- automatic captions, so no flag ever establishes that a recording has none.
 SELECT m.event_id,count(*) AS videos,
  count(DISTINCT CASE WHEN v.has_caption OR coalesce(array_length(r.tracks),0)>0 THEN m.video_key END) AS observed
 FROM linked_videos m LEFT JOIN videos_export v ON m.video_key=v.video_key LEFT JOIN recordings_export r ON m.video_key=r.video_key
 GROUP BY m.event_id
), caption_rows AS (
 SELECT e.event_id,'captions' AS aspect,
  CASE WHEN c.observed>0 THEN 'present' WHEN c.event_id IS NOT NULL THEN 'unknown' ELSE 'not_stated' END AS state,
  'videos.has_caption,recordings.tracks' AS basis,cast(coalesce(c.observed,0) AS INT) AS count
 FROM meetings_export e LEFT JOIN caption_counts c ON e.event_id=c.event_id
)
SELECT event_id,aspect,state,basis,count,CASE WHEN state='unresolved' THEN 'old_evidence_disputes_negative_verdict' WHEN state='claimed' THEN 'video_text_only' WHEN state='partial' THEN 'excerpts_only' END AS reason FROM recording_rows
UNION ALL SELECT event_id,aspect,state,basis,count,cast(NULL AS VARCHAR) FROM transcript_rows
UNION ALL SELECT event_id,aspect,state,basis,count,cast(NULL AS VARCHAR) FROM document_rows
UNION ALL SELECT event_id,aspect,state,basis,count,cast(NULL AS VARCHAR) FROM witness_rows
UNION ALL SELECT event_id,aspect,state,basis,count,cast(NULL AS VARCHAR) FROM caption_rows
