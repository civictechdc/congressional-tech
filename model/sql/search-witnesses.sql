WITH witnesses AS (
 SELECT w.*,regexp_match(w.package_id,'(?i)^CHRG-([0-9]+)([hsj])hrg') AS package_parts FROM witnesses_export w
)
SELECT 'witnesses' AS source_id,w.witness_key AS member_key,
 coalesce(w.name,'Witness '||w.witness_key) AS title,
 '?tab=witnesses&witness='||w.witness_key AS link,
 concat_ws(' | ',w.position,w.organization,w.on_behalf_of,w.panel,f.title) AS context,
 btrim(json_array(named_struct('position',w.position,'organization',w.organization,'on_behalf_of',w.on_behalf_of,
  'location',w.location,'panel',w.panel,'panel_order',w.panel_order,'display_order',w.display_order,
  'testified',w.testified,'bioguide_id',w.bioguide_id,'occasion',w.occasion,'event_id',w.event_id,
  'package_id',w.package_id,'page_url',w.page_url,'meeting_title',f.title)),'[]') AS metadata,
 f.meeting_date AS date,cast(NULL AS DATE) AS first_captured,
 make_array(w.witness_key,w.bioguide_id,cast(w.event_id AS VARCHAR),w.package_id) AS identifiers,
 make_array('witness') AS record_kind,
 make_array(coalesce(f.chamber,
  CASE lower(w.package_parts[2]) WHEN 'h' THEN 'house' WHEN 's' THEN 'senate' WHEN 'j' THEN 'joint' END,
  CASE WHEN w.occasion LIKE 'page:%' THEN 'senate' END)) AS chamber,
 f.committee_codes AS committee,make_array(coalesce(f.congress,w.package_parts[1])) AS congress,
 cast(NULL AS VARCHAR[]) AS document_kind,cast(NULL AS VARCHAR[]) AS format,cast(NULL AS VARCHAR[]) AS meeting_type,
 cast(NULL AS VARCHAR[]) AS status,make_array(w.witness_type) AS witness_type,
 cast(NULL AS VARCHAR[]) AS has_video,cast(NULL AS VARCHAR[]) AS has_transcript
FROM search_meeting_facts f RIGHT JOIN witnesses w ON w.event_id=f.event_id
