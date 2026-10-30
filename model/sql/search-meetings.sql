WITH parts AS (
 SELECT event_id,1 AS part,committee_names AS text FROM search_meeting_facts WHERE committee_names<>''
 UNION ALL
 SELECT event_id,2,array_to_string(array_sort(array_distinct(array_agg(concat_ws(', ',name,position,organization)))),' | ')
 FROM witnesses_export WHERE event_id IS NOT NULL
 GROUP BY event_id
 UNION ALL
 SELECT k.event_id,3,array_to_string(array_sort(array_distinct(array_agg(b.title))),' | ')
 FROM (SELECT event_id,unnest(subject_keys) AS bill_id FROM meetings_export) k
 JOIN bills_export b ON b.bill_id=k.bill_id
 WHERE b.title IS NOT NULL
 GROUP BY k.event_id
 UNION ALL
 SELECT event_id,4,array_to_string(array_sort(array_distinct(array_agg(title))),' | ')
 FROM (SELECT title,try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM details WHERE NOT hidden AND title IS NOT NULL)
 WHERE event_id IS NOT NULL
 GROUP BY event_id
), context AS (
 SELECT event_id,array_to_string(array_agg(text ORDER BY part),' | ') AS text FROM parts GROUP BY event_id
), transcript_packages AS (
 SELECT event_id,array_agg(package_id) AS packages
 FROM (SELECT event_id,unnest(transcripts)['package_id'] AS package_id FROM meetings_export)
 GROUP BY event_id
), video_keys AS (
 SELECT event_id,array_agg(video_key) AS video_keys
 FROM (SELECT event_id,unnest(videos)['video_key'] AS video_key FROM meetings_export)
 GROUP BY event_id
)
SELECT 'meetings' AS source_id,cast(m.event_id AS VARCHAR) AS member_key,
 coalesce(m.title,'Meeting '||cast(m.event_id AS VARCHAR)) AS title,
 '?tab=hearings&hearing='||cast(m.event_id AS VARCHAR) AS link,
 coalesce(c.text,'') AS context,
 btrim(json_array(named_struct('session',m.session,'committees',m.committees,'subject_keys',m.subject_keys,
  'transcript_packages',p.packages,'videos',m.videos)),'[]') AS metadata,
 m.meeting_date AS date,cast(NULL AS DATE) AS first_captured,
 array_concat(make_array(cast(m.event_id AS VARCHAR)),m.subject_keys,p.packages,v.video_keys) AS identifiers,
 make_array('meeting') AS record_kind,make_array(m.chamber) AS chamber,f.committee_codes AS committee,
 make_array(f.congress) AS congress,cast(NULL AS VARCHAR[]) AS document_kind,cast(NULL AS VARCHAR[]) AS format,
 make_array(m.meeting_type) AS meeting_type,make_array(m.status) AS status,cast(NULL AS VARCHAR[]) AS witness_type,
 make_array(CASE WHEN f.has_record THEN CASE WHEN cardinality(m.videos)>0 THEN 'true' ELSE 'false' END END) AS has_video,
 make_array(CASE WHEN f.has_record THEN CASE WHEN cardinality(m.transcripts)>0 THEN 'true' ELSE 'false' END END) AS has_transcript
FROM search_meeting_facts f
JOIN meetings_export m ON m.event_id=f.event_id
LEFT JOIN context c ON m.event_id=c.event_id
LEFT JOIN transcript_packages p ON m.event_id=p.event_id
LEFT JOIN video_keys v ON m.event_id=v.event_id
