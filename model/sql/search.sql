WITH search_rows AS (
 SELECT * FROM search_documents
 UNION ALL SELECT * FROM search_meetings
 UNION ALL SELECT * FROM search_witnesses
), committee_parents AS (
 SELECT r.source_id,r.member_key,array_agg(c.parent_system_code) AS parents
 FROM (SELECT source_id,member_key,unnest(committee) AS system_code FROM search_rows) r
 JOIN committees_export c ON c.system_code=r.system_code
 WHERE c.parent_system_code IS NOT NULL
 GROUP BY r.source_id,r.member_key
), canonical AS (
 SELECT r.source_id,r.member_key,r.title,
  'https://civictechdc.github.io/congressional-tech/archive/'||r.link AS url,
  r.context,r.metadata,r.date,r.first_captured,
  array_sort(array_except(coalesce(r.identifiers,x.empty),x.blanks)) AS identifiers,
  array_sort(array_except(coalesce(r.record_kind,x.empty),x.blanks)) AS record_kind,
  array_sort(array_except(coalesce(r.chamber,x.empty),x.blanks)) AS chamber,
  array_sort(array_except(coalesce(r.committee,x.empty),x.blanks)) AS committee,
  array_sort(array_except(array_concat(coalesce(r.committee,x.empty),p.parents),x.blanks)) AS committee_expanded,
  array_sort(array_except(coalesce(r.congress,x.empty),x.blanks)) AS congress,
  array_sort(array_except(coalesce(r.document_kind,x.empty),x.blanks)) AS document_kind,
  array_sort(array_except(coalesce(r.format,x.empty),x.blanks)) AS format,
  array_sort(array_except(coalesce(r.meeting_type,x.empty),x.blanks)) AS meeting_type,
  array_sort(array_except(coalesce(r.status,x.empty),x.blanks)) AS status,
  array_sort(array_except(coalesce(r.witness_type,x.empty),x.blanks)) AS witness_type,
  array_sort(array_except(coalesce(r.has_video,x.empty),x.blanks)) AS has_video,
  array_sort(array_except(coalesce(r.has_transcript,x.empty),x.blanks)) AS has_transcript
 FROM committee_parents p RIGHT JOIN (
  (SELECT cast(make_array() AS VARCHAR[]) AS empty,make_array(cast(NULL AS VARCHAR),'') AS blanks) x
  CROSS JOIN search_rows r
 ) ON r.source_id=p.source_id AND r.member_key=p.member_key
)
SELECT encode(sha256(json_array(source_id,member_key)),'hex') AS id,source_id,member_key,
 substr(encode(sha256(json_array(source_id,member_key,title,url,context,identifiers,metadata,cast(date AS VARCHAR),
  cast(first_captured AS VARCHAR),record_kind,chamber,committee,committee_expanded,congress,document_kind,format,
  meeting_type,status,witness_type,has_video,has_transcript)),'hex'),1,16) AS source_occurrence_id,
 title,url,context,identifiers,metadata,date,first_captured,record_kind,chamber,committee,committee_expanded,
 congress,document_kind,format,meeting_type,status,witness_type,has_video,has_transcript
FROM canonical
