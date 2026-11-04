-- One materialized row per selected appearance record and capture context, without its appearance
-- list. appearance_records_resolved ranks these narrow rows and re-reads the lists of the selected
-- ones by (record_sha_hex,source), the selected records' key. Inlined, this chain (and its captures
-- join) was planned once per reference: six copies.
WITH candidate_appearance_shas AS (
 -- The raw binary digest, so captures probes this small candidate set instead of being the hash
 -- build (2.07M rows, 1.33 GB) behind an expression key (AGENTS.md).
 SELECT DISTINCT arrow_cast(decode(record_sha_hex,'hex'),'FixedSizeBinary(32)') AS sha256
 FROM selected_appearance_records
 WHERE record_sha_hex IS NOT NULL
), capture_contexts AS (
 SELECT
  encode(c.sha256,'hex') AS record_sha_hex,
  CASE
   WHEN coalesce(c.sniffed_format,'') NOT IN ('html','pdf','zip','vtt','m3u8')
    AND lower(coalesce(c.media_type,'')) NOT LIKE '%html%'
    AND lower(coalesce(c.url,c.requested_url,'')) NOT LIKE '%.html%'
    AND (c.family='congress/meetings'
     OR regexp_like(coalesce(c.url,c.requested_url,''),'(?i)(?:api[.]|www[.])?congress[.]gov/(?:v3/)?committee-meeting/[0-9]+/(?:house|senate|joint|nochamber)/[0-9]+')
     OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%api.congress.gov%/committee-meeting%'
     OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%congress.gov/committee-meeting%') THEN 'congress_gov'
   WHEN (upper(coalesce(c.url,'')) LIKE '%CHRG%'
     OR upper(coalesce(c.requested_url,'')) LIKE '%CHRG%'
     OR upper(coalesce(c.context_url,'')) LIKE '%CHRG%'
     OR upper(coalesce(c.member_path,'')) LIKE '%CHRG%')
    AND (c.family='govinfo/mods'
     OR ((lower(coalesce(c.url,'')) LIKE '%mods%'
       OR lower(coalesce(c.requested_url,'')) LIKE '%mods%'
       OR lower(coalesce(c.context_url,'')) LIKE '%mods%'
       OR lower(coalesce(c.member_path,'')) LIKE '%mods%')
      AND (coalesce(c.sniffed_format,'')='xml'
       OR lower(coalesce(c.media_type,'')) LIKE '%xml%'
       OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%.xml%'
       OR lower(coalesce(c.context_url,'')) LIKE '%/mods%'
       OR lower(coalesce(c.member_path,'')) LIKE '%.xml%'))) THEN 'mods'
   WHEN c.member_path IS NULL
    AND coalesce(c.family,'')<>'documents'
    AND coalesce(c.sniffed_format,'') NOT IN ('pdf','xml','json','zip','vtt','m3u8')
    AND lower(coalesce(c.media_type,'')) NOT LIKE '%pdf%'
    AND lower(coalesce(c.url,c.requested_url,'')) NOT LIKE '%.pdf%'
    AND (c.family IN ('senate/hearings','senate/pages','senate/hearing-page')
     OR (lower(coalesce(c.url,c.requested_url,'')) LIKE '%.senate.gov%'
      AND (lower(coalesce(c.url,c.requested_url,'')) LIKE '%hearing%'
       OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%meeting%'
       OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%business%'))) THEN 'senate_page'
   ELSE 'house_xml'
  END AS source,
  coalesce(c.url,c.requested_url,c.context_url) AS source_url,
  c.member_path,
  max(arrow_cast(try_cast(c.retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS retrieved_at
 FROM captures c
 JOIN candidate_appearance_shas cas ON c.sha256=cas.sha256
 WHERE c.mode='fetch' AND c.complete AND c.outcome IN ('stored','unchanged')
  AND c.http_status BETWEEN 200 AND 299 AND c.sha256 IS NOT NULL
 GROUP BY c.sha256,
  CASE
   WHEN coalesce(c.sniffed_format,'') NOT IN ('html','pdf','zip','vtt','m3u8')
    AND lower(coalesce(c.media_type,'')) NOT LIKE '%html%'
    AND lower(coalesce(c.url,c.requested_url,'')) NOT LIKE '%.html%'
    AND (c.family='congress/meetings'
     OR regexp_like(coalesce(c.url,c.requested_url,''),'(?i)(?:api[.]|www[.])?congress[.]gov/(?:v3/)?committee-meeting/[0-9]+/(?:house|senate|joint|nochamber)/[0-9]+')
     OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%api.congress.gov%/committee-meeting%'
     OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%congress.gov/committee-meeting%') THEN 'congress_gov'
   WHEN (upper(coalesce(c.url,'')) LIKE '%CHRG%'
     OR upper(coalesce(c.requested_url,'')) LIKE '%CHRG%'
     OR upper(coalesce(c.context_url,'')) LIKE '%CHRG%'
     OR upper(coalesce(c.member_path,'')) LIKE '%CHRG%')
    AND (c.family='govinfo/mods'
     OR ((lower(coalesce(c.url,'')) LIKE '%mods%'
       OR lower(coalesce(c.requested_url,'')) LIKE '%mods%'
       OR lower(coalesce(c.context_url,'')) LIKE '%mods%'
       OR lower(coalesce(c.member_path,'')) LIKE '%mods%')
      AND (coalesce(c.sniffed_format,'')='xml'
       OR lower(coalesce(c.media_type,'')) LIKE '%xml%'
       OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%.xml%'
       OR lower(coalesce(c.context_url,'')) LIKE '%/mods%'
       OR lower(coalesce(c.member_path,'')) LIKE '%.xml%'))) THEN 'mods'
   WHEN c.member_path IS NULL
    AND coalesce(c.family,'')<>'documents'
    AND coalesce(c.sniffed_format,'') NOT IN ('pdf','xml','json','zip','vtt','m3u8')
    AND lower(coalesce(c.media_type,'')) NOT LIKE '%pdf%'
    AND lower(coalesce(c.url,c.requested_url,'')) NOT LIKE '%.pdf%'
    AND (c.family IN ('senate/hearings','senate/pages','senate/hearing-page')
     OR (lower(coalesce(c.url,c.requested_url,'')) LIKE '%.senate.gov%'
      AND (lower(coalesce(c.url,c.requested_url,'')) LIKE '%hearing%'
       OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%meeting%'
       OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%business%'))) THEN 'senate_page'
   ELSE 'house_xml'
  END,
  coalesce(c.url,c.requested_url,c.context_url),c.member_path
), meeting_updates AS (
 SELECT record_sha_hex,
  max(arrow_cast(try_cast(m['updated'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS updated
 FROM (
  SELECT r.record_sha_hex,unnest(r.meetings) AS m
  FROM selected_meeting_records r
  WHERE r.status='completed' AND r.meetings IS NOT NULL
 ) GROUP BY record_sha_hex
), linked_house_lists AS (
 SELECT record_sha_hex,unnest(appearances) AS a FROM selected_appearance_records
 WHERE source='house_xml' AND status='completed' AND event_id IS NULL AND appearances IS NOT NULL
), house_list_links AS (
 SELECT record_sha_hex,trim(unnest(a['document_links'])) AS link FROM linked_house_lists
), stated_list_events AS (
 -- ct-x78c: a House witness list with no meeting-id still states its event, in its own document
 -- links (/meetings/<c>/<sc>/<yyyymmdd>/<event>/) and in its retained file name (wlist/<event>.xml).
 SELECT record_sha_hex,try_cast((regexp_match(link,'(?i)/meetings/[A-Za-z0-9]+/[A-Za-z0-9]+/[0-9]{8}/([0-9]+)/'))[1] AS BIGINT) AS event_id
 FROM house_list_links
 UNION ALL
 -- Retained lists name their event only in the receipt's file path; those rows are not good fetches,
 -- so every capture row of the body counts (captures.original_path, relative paths only).
 SELECT h.record_sha_hex,try_cast((regexp_match(c.original_path,'(?i)(?:^|/)wlist/([0-9]+)[.]xml$'))[1] AS BIGINT)
 FROM captures c
 -- Join on the raw binary digest so the small candidate set prunes the captures scan (AGENTS.md).
 JOIN (SELECT DISTINCT record_sha_hex,arrow_cast(decode(record_sha_hex,'hex'),'FixedSizeBinary(32)') AS sha256
  FROM selected_appearance_records
  WHERE source='house_xml' AND status='completed' AND event_id IS NULL) h ON c.sha256=h.sha256
 WHERE c.original_path IS NOT NULL
), list_events AS (
 -- One event only: links or paths that disagree state no event.
 SELECT record_sha_hex,min(event_id) AS event_id FROM stated_list_events WHERE event_id IS NOT NULL
 GROUP BY record_sha_hex HAVING min(event_id)=max(event_id)
), bound_contexts AS (
 SELECT
  r.record_sha_hex,
  r.parser_version,
  r.status,
  r.error_type,
  r.source,
  ms.priority,
  u.updated,
  cc.retrieved_at,
  coalesce(cc.source_url,r.context_url) AS source_url,
  cc.member_path,
  encode(sha256(json_array(coalesce(cc.source_url,r.context_url),cc.member_path)),'hex') AS context_key,
  coalesce(
   try_cast(r.event_id AS BIGINT),
   try_cast((regexp_match(coalesce(cc.source_url,r.context_url,''),'(?i)/committee-meeting/[0-9]+/(?:house|senate|joint|nochamber)/([0-9]+)'))[1] AS BIGINT),
   try_cast((regexp_match(coalesce(cc.source_url,r.context_url,''),'(?i)/meetings/[A-Za-z0-9]+/[A-Za-z0-9]+/[0-9]{8}/([0-9]+)/'))[1] AS BIGINT),
   try_cast((regexp_match(coalesce(cc.source_url,r.context_url,''),'(?i)[?&]eventid=([0-9]+)'))[1] AS BIGINT),
   le.event_id
  ) AS raw_event_id,
  coalesce(
   nullif(trim(r.package_id),''),
   (regexp_match(coalesce(cc.source_url,''),'(?i)(CHRG-[0-9]+[hsj]hrg[0-9]+)'))[1],
   (regexp_match(coalesce(cc.member_path,''),'(?i)(CHRG-[0-9]+[hsj]hrg[0-9]+)'))[1],
   (regexp_match(coalesce(r.context_url,''),'(?i)(CHRG-[0-9]+[hsj]hrg[0-9]+)'))[1]
  ) AS package_id,
  CASE WHEN r.source='senate_page' THEN coalesce(cc.source_url,r.context_url) END AS page_url,
  nullif(trim(r.declared_base),'') AS declared_base,
  CASE
   WHEN r.status<>'completed' THEN 'failed'
   -- An empty House list made before its hearing is a placeholder, not a statement that no one testified
   -- (111420's was created 2021-04-07 for a 2021-04-15 hearing), so it blocks no other source.
   WHEN r.source='house_xml' AND r.collection_state='empty' AND md.meeting_date IS NOT NULL
    AND try_cast(substr(r.created,1,10) AS DATE)<md.meeting_date THEN 'absent'
   ELSE coalesce(
    nullif(trim(r.collection_state),''),
    CASE
     WHEN coalesce(array_length(r.appearances),0)>0 THEN 'present'
     ELSE 'empty'
    END
   )
  END AS collection_state
 FROM selected_appearance_records r
 JOIN meeting_sources ms ON ms.kind='appearance' AND r.source=ms.source
 LEFT JOIN capture_contexts cc ON r.record_sha_hex=cc.record_sha_hex AND r.source=cc.source
 LEFT JOIN meeting_updates u ON r.record_sha_hex=u.record_sha_hex
 LEFT JOIN list_events le ON r.source='house_xml' AND r.record_sha_hex=le.record_sha_hex
 LEFT JOIN (SELECT event_id,meeting_date FROM meetings_resolved) md ON r.source='house_xml' AND md.event_id=r.event_id
), observations_with_occasion AS (
 SELECT
  b.*,
  CASE
   WHEN b.source IN ('house_xml','congress_gov') AND b.raw_event_id IS NOT NULL
    THEN 'meeting:'||cast(b.raw_event_id AS VARCHAR)
   WHEN b.source='mods' AND spm.event_id IS NOT NULL
    THEN 'meeting:'||cast(spm.event_id AS VARCHAR)
   WHEN b.source='mods' AND b.package_id IS NOT NULL
    THEN 'package:'||b.package_id
   WHEN b.source='senate_page' AND b.collection_state='present' AND coalesce(b.raw_event_id,spml.event_id) IS NOT NULL
    THEN 'meeting:'||cast(coalesce(b.raw_event_id,spml.event_id) AS VARCHAR)
   WHEN b.source='senate_page' AND pk.url_key IS NOT NULL
    THEN 'page:'||substr(encode(sha256(pk.url_key),'hex'),1,16)
  END AS occasion,
  CASE
   WHEN b.source IN ('house_xml','congress_gov') THEN b.raw_event_id
   WHEN b.source='mods' THEN spm.event_id
   WHEN b.source='senate_page' AND b.collection_state='present' THEN coalesce(b.raw_event_id,spml.event_id)
  END AS event_id,
  CASE
   WHEN b.source_url IS NOT NULL AND b.declared_base IS NOT NULL
    THEN coalesce(url_resolve(b.declared_base,b.source_url),b.source_url)
   ELSE b.source_url
  END AS resolved_base
 FROM bound_contexts b
 LEFT JOIN package_meeting_links spm ON b.source='mods' AND b.package_id=spm.package_id
 LEFT JOIN senate_page_meeting_links spml ON b.source='senate_page' AND b.record_sha_hex=spml.record_sha_hex
 LEFT JOIN appearance_url_keys pk ON b.source='senate_page' AND b.page_url=pk.url AND pk.error IS NULL
)
 SELECT *,
  CASE
   WHEN status<>'completed' OR collection_state IN ('failed','unrecognized') THEN 'unresolved'
   ELSE collection_state
  END AS effective_state
 FROM observations_with_occasion
 WHERE occasion IS NOT NULL
