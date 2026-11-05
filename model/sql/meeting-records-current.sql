-- One current record per (event, source), each collection taken from the record meeting-records-ranked
-- picked for it. The picks are rows of that materialized step, so these joins rescan nothing.
SELECT w.record_sha_hex,w.source,w.priority,w.retrieved_at,w.event_id,w.chamber,w.congress,w.session,w.updated,
 w.updated_literal,w.title,w.meeting_date,w.meeting_type,w.status,
 s.sittings,c.committees,k.subject_keys,j.transcript_jackets,v.videos,d.document_urls,
 w.collection_states,w.access,w.access_basis,w.not_held,w.title_key,w.reschedule_candidate,w.rn,
 s.sittings_state,c.committees_state,k.subjects_state,j.jackets_state,v.videos_state,d.document_urls_state
FROM meeting_records_ranked w
LEFT JOIN meeting_records_ranked s ON s.event_id=w.event_id AND s.source=w.source AND s.rn=w.sittings_rn
LEFT JOIN meeting_records_ranked c ON c.event_id=w.event_id AND c.source=w.source AND c.rn=w.committees_rn
LEFT JOIN meeting_records_ranked k ON k.event_id=w.event_id AND k.source=w.source AND k.rn=w.subjects_rn
LEFT JOIN meeting_records_ranked j ON j.event_id=w.event_id AND j.source=w.source AND j.rn=w.jackets_rn
LEFT JOIN meeting_records_ranked v ON v.event_id=w.event_id AND v.source=w.source AND v.rn=w.videos_rn
LEFT JOIN meeting_records_ranked d ON d.event_id=w.event_id AND d.source=w.source AND d.rn=w.document_urls_rn
WHERE w.rn=1
