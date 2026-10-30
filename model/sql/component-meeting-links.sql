WITH transcript_links AS (
 SELECT DISTINCT s.component,l.event_id,l.meeting_date
 FROM saved_files s
 JOIN source_annotations a ON s.source_id=a.source_id
 LEFT JOIN document_packages pk ON s.component=pk.component
 JOIN meeting_transcript_links l ON coalesce(pk.package_id,a.package_id)=l.package_id
 UNION
 SELECT DISTINCT r.component,l.event_id,l.meeting_date
 FROM saved_recoveries r
 JOIN effective_filenames n ON n.input_id='recovery:'||r.id
 JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
 JOIN source_annotations a ON f.source_id=a.source_id
 JOIN meeting_transcript_links l ON a.package_id=l.package_id
), existing_keys AS (
 SELECT m.component,try_cast(unnest(m.meeting_keys) AS BIGINT) AS event_id
 FROM document_metadata m WHERE m.meeting_keys IS NOT NULL
 UNION
 SELECT r.component,try_cast(unnest(a.meeting_keys) AS BIGINT) AS event_id
 FROM saved_recoveries r
 JOIN effective_filenames n ON n.input_id='recovery:'||r.id
 JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
 JOIN source_annotations a ON f.source_id=a.source_id
 WHERE a.meeting_keys IS NOT NULL
), all_component_meetings AS (
 SELECT component,event_id FROM transcript_links
 UNION
 SELECT component,event_id FROM existing_keys WHERE event_id IS NOT NULL
), dated AS (
 SELECT cm.component,cm.event_id,mr.meeting_date
 FROM all_component_meetings cm
 LEFT JOIN meetings_resolved mr ON cm.event_id=mr.event_id
)
SELECT component,
 array_sort(array_distinct(array_agg(cast(event_id AS VARCHAR)))) AS meeting_keys,
 min(meeting_date) AS meeting_date
FROM dated GROUP BY component
