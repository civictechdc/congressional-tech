WITH documents AS (
 SELECT encode(link_key,'hex') AS member_key,filename,title,document_kind,committee_keys,chambers,congress,format,
  document_date,first_captured,date_kind,saved_kind,meeting_keys,measure_keys,bioguide_ids,witness_keys,
  document_date_source,package_id
 FROM details WHERE NOT hidden
), parts AS (
 SELECT k.member_key,1 AS part,array_to_string(array_sort(array_distinct(array_agg(f.title))),' | ') AS text
 FROM (SELECT encode(link_key,'hex') AS member_key,try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM details WHERE NOT hidden) k
 JOIN search_meeting_facts f ON f.event_id=k.event_id
 WHERE f.title IS NOT NULL
 GROUP BY k.member_key
 UNION ALL
 SELECT k.member_key,2,array_to_string(array_sort(array_distinct(array_agg(concat_ws(', ',w.name,w.organization)))),' | ')
 FROM (SELECT encode(link_key,'hex') AS member_key,unnest(witness_keys) AS witness_key FROM details WHERE NOT hidden) k
 JOIN witnesses_export w ON w.witness_key=k.witness_key
 GROUP BY k.member_key
 UNION ALL
 SELECT member_key,3,array_to_string(array_sort(array_distinct(array_agg(value))),' ')
 FROM (SELECT encode(link_key,'hex') AS member_key,unnest(facts)['value'] AS value FROM details WHERE NOT hidden)
 WHERE value IS NOT NULL AND value<>''
 GROUP BY member_key
), context AS (
 SELECT member_key,array_to_string(array_agg(text ORDER BY part),' | ') AS text FROM parts GROUP BY member_key
)
SELECT 'documents' AS source_id,d.member_key,
 coalesce(d.title,nullif(d.filename,''),'Document '||d.member_key) AS title,
 '?key='||d.member_key AS link,
 concat_ws(' | ',CASE WHEN d.title IS NOT NULL THEN nullif(d.filename,'') END,c.text) AS context,
 btrim(json_array(named_struct('filename',nullif(d.filename,''),'document_date_source',d.document_date_source,
  'date_kind',d.date_kind,'saved_kind',d.saved_kind,'package_id',d.package_id,'meeting_keys',d.meeting_keys,
  'measure_keys',d.measure_keys,'witness_keys',d.witness_keys,'bioguide_ids',d.bioguide_ids)),'[]') AS metadata,
 d.document_date AS date,d.first_captured,
 array_concat(make_array(d.member_key,d.package_id),d.measure_keys,d.meeting_keys) AS identifiers,
 make_array('document') AS record_kind,d.chambers AS chamber,d.committee_keys AS committee,
 make_array(cast(d.congress AS VARCHAR)) AS congress,d.document_kind,make_array(d.format) AS format,
 cast(NULL AS VARCHAR[]) AS meeting_type,cast(NULL AS VARCHAR[]) AS status,cast(NULL AS VARCHAR[]) AS witness_type,
 cast(NULL AS VARCHAR[]) AS has_video,cast(NULL AS VARCHAR[]) AS has_transcript
FROM context c RIGHT JOIN documents d ON c.member_key=d.member_key
