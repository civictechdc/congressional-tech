WITH target AS (SELECT CAST(? AS BIGINT) AS event_id), observations AS (
 SELECT r.match_id,r.subject_kind,r.subject_id,r.event_id,r.package_id,r.video_key,r.url,r.basis,r.decision,r.score,r.recording_scope,r.status,r.note,r.source_ref,
  list_filter(r.meeting_links,lambda l:l.event_id=t.event_id) AS meeting_links
 FROM recording_matches r CROSS JOIN target t
)
SELECT * FROM observations WHERE len(meeting_links)>0 ORDER BY match_id LIMIT 100