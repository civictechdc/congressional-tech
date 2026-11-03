WITH vetted_transcript_links AS (
 SELECT package_id,event_id FROM package_meeting_links
 UNION
 SELECT l.package_id,l.event_id FROM meeting_transcript_links l
 LEFT JOIN package_mods_facts f ON f.package_id=l.package_id WHERE f.package_id IS NULL
), transcript_links AS (
 SELECT DISTINCT s.component,l.event_id
 FROM saved_files s
 JOIN source_annotations a ON s.source_id=a.source_id
 LEFT JOIN document_packages pk ON s.component=pk.component
 JOIN vetted_transcript_links l ON coalesce(pk.package_id,a.package_id)=l.package_id
 UNION
 SELECT DISTINCT r.component,l.event_id
 FROM saved_recoveries r
 JOIN effective_filenames n ON n.input_id='recovery:'||r.id
 JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
 JOIN source_annotations a ON f.source_id=a.source_id
 JOIN vetted_transcript_links l ON a.package_id=l.package_id
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
), witness_meetings AS (
 SELECT DISTINCT dwk.component,w.event_id
 FROM (SELECT component,unnest(witness_keys) AS witness_key FROM document_witness_keys WHERE witness_keys IS NOT NULL) dwk
 JOIN appearance_records_resolved w ON w.witness_key=dwk.witness_key
 WHERE w.event_id IS NOT NULL
), all_component_meetings AS (
 SELECT component,event_id FROM transcript_links
 UNION
 SELECT component,event_id FROM existing_keys WHERE event_id IS NOT NULL
 UNION
 SELECT component,event_id FROM witness_meetings
), dated AS (
 SELECT cm.component,cm.event_id,mr.meeting_date,
  nullif(lower(trim(mr.chamber)),'') AS chamber,
  cast(mr.congress AS SMALLINT) AS congress
 FROM all_component_meetings cm
 LEFT JOIN meetings_resolved mr ON cm.event_id=mr.event_id
), meeting_committees AS (
 SELECT cm.component,nullif(lower(trim(mc.c['system_code'])),'') AS committee_key
 FROM all_component_meetings cm
 JOIN (SELECT event_id,unnest(committees) AS c FROM meetings_resolved WHERE committees IS NOT NULL) mc
  ON mc.event_id=cm.event_id
 WHERE mc.c['system_code'] IS NOT NULL AND trim(mc.c['system_code'])<>''
), committee_agg AS (
 SELECT component,
  array_sort(array_distinct(array_agg(committee_key))) AS committee_keys
 FROM meeting_committees
 WHERE committee_key IS NOT NULL
 GROUP BY component
), meeting_agg AS (
 SELECT component,
  array_sort(array_distinct(array_agg(cast(event_id AS VARCHAR)))) AS meeting_keys,
  min(meeting_date) AS meeting_date,
  array_sort(array_distinct(array_agg(chamber) FILTER (WHERE chamber IS NOT NULL))) AS chambers,
  min(congress) AS congress
 FROM dated
 GROUP BY component
)
SELECT
 ma.component,
 ma.meeting_keys,
 ma.meeting_date,
 coalesce(ca.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS committee_keys,
 coalesce(ma.chambers,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS chambers,
 ma.congress
FROM meeting_agg ma
LEFT JOIN committee_agg ca ON ca.component=ma.component
