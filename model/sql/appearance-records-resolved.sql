WITH candidate_appearance_shas AS (
 SELECT DISTINCT record_sha_hex
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
 JOIN candidate_appearance_shas cas ON encode(c.sha256,'hex')=cas.record_sha_hex
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
 SELECT encode(c.sha256,'hex'),try_cast((regexp_match(c.original_path,'(?i)(?:^|/)wlist/([0-9]+)[.]xml$'))[1] AS BIGINT)
 FROM captures c
 JOIN (SELECT DISTINCT record_sha_hex FROM selected_appearance_records
  WHERE source='house_xml' AND status='completed' AND event_id IS NULL) h ON encode(c.sha256,'hex')=h.record_sha_hex
 WHERE c.original_path IS NOT NULL
), list_events AS (
 -- One event only: links or paths that disagree state no event.
 SELECT record_sha_hex,min(event_id) AS event_id FROM stated_list_events WHERE event_id IS NOT NULL
 GROUP BY record_sha_hex HAVING count(DISTINCT event_id)=1
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
   ELSE coalesce(
    nullif(trim(r.collection_state),''),
    CASE
     WHEN coalesce(array_length(r.appearances),0)>0 THEN 'present'
     ELSE 'empty'
    END
   )
  END AS collection_state,
  r.appearances
 FROM selected_appearance_records r
 JOIN meeting_sources ms ON ms.kind='appearance' AND r.source=ms.source
 LEFT JOIN capture_contexts cc ON r.record_sha_hex=cc.record_sha_hex AND r.source=cc.source
 LEFT JOIN meeting_updates u ON r.record_sha_hex=u.record_sha_hex
 LEFT JOIN list_events le ON r.source='house_xml' AND r.record_sha_hex=le.record_sha_hex
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
   WHEN b.source='senate_page' AND pk.url_key IS NOT NULL
    THEN 'page:'||substr(encode(sha256(pk.url_key),'hex'),1,16)
  END AS occasion,
  CASE
   WHEN b.source IN ('house_xml','congress_gov') THEN b.raw_event_id
   WHEN b.source='mods' THEN spm.event_id
   ELSE b.raw_event_id
  END AS event_id,
  CASE
   WHEN b.source_url IS NOT NULL AND b.declared_base IS NOT NULL
    THEN coalesce(url_resolve(b.declared_base,b.source_url),b.source_url)
   ELSE b.source_url
  END AS resolved_base
 FROM bound_contexts b
 LEFT JOIN package_meeting_links spm ON b.source='mods' AND b.package_id=spm.package_id
 LEFT JOIN appearance_url_keys pk ON b.source='senate_page' AND b.page_url=pk.url AND pk.error IS NULL
), valid_observations AS (
 SELECT *,
  CASE
   WHEN status<>'completed' OR collection_state IN ('failed','unrecognized') THEN 'unresolved'
   ELSE collection_state
  END AS effective_state
 FROM observations_with_occasion
 WHERE occasion IS NOT NULL
), ranked_context_observations AS (
 SELECT *,
  row_number() OVER(
   PARTITION BY occasion,source,context_key
   ORDER BY (effective_state IN ('present','empty')) DESC,(effective_state='absent') ASC,updated DESC NULLS LAST,retrieved_at DESC NULLS LAST,(effective_state='present') DESC,record_sha_hex ASC
  ) AS ctx_rn
 FROM valid_observations
), current_context_observations AS (
 SELECT *
 FROM ranked_context_observations
 WHERE ctx_rn=1
), superseded_source_bodies AS (
 SELECT DISTINCT old.occasion,old.source,old.record_sha_hex
 FROM ranked_context_observations old
 JOIN current_context_observations cur
  ON old.occasion=cur.occasion AND old.source=cur.source AND old.context_key=cur.context_key
 WHERE old.ctx_rn>1 AND old.record_sha_hex<>cur.record_sha_hex
), ranked_source_observations AS (
 SELECT c.*,
  row_number() OVER(
   PARTITION BY c.occasion,c.source
   ORDER BY (c.effective_state IN ('present','empty')) DESC,(c.effective_state='absent') ASC,(sb.record_sha_hex IS NOT NULL) ASC,c.updated DESC NULLS LAST,c.retrieved_at DESC NULLS LAST,(c.effective_state='present') DESC,c.record_sha_hex ASC,c.context_key ASC
  ) AS obs_rn
 FROM current_context_observations c
 LEFT JOIN superseded_source_bodies sb
  ON c.occasion=sb.occasion AND c.source=sb.source AND c.record_sha_hex=sb.record_sha_hex
), current_source_observations AS (
 SELECT *
 FROM ranked_source_observations
 WHERE obs_rn=1
), winning_source_per_occasion AS (
 SELECT *,
  row_number() OVER(
   PARTITION BY occasion
   ORDER BY priority ASC
  ) AS src_rn
 FROM current_source_observations
 WHERE effective_state IN ('present','empty','unresolved')
), selected_observations AS (
 SELECT *
 FROM winning_source_per_occasion
 WHERE src_rn=1 AND effective_state='present'
), unnested_occurrences AS (
 SELECT
  s.record_sha_hex,
  s.source,
  s.occasion,
  s.context_key,
  s.event_id,
  s.package_id,
  s.page_url,
  s.resolved_base,
  unnest(s.appearances) AS a,
  unnest(range(0,cast(array_length(s.appearances) AS BIGINT))) AS ordinal
 FROM selected_observations s
 WHERE s.appearances IS NOT NULL AND coalesce(array_length(s.appearances),0)>0
), extracted_occurrences AS (
 SELECT
  record_sha_hex,
  source,
  occasion,
  context_key,
  event_id,
  package_id,
  page_url,
  resolved_base,
  ordinal,
  coalesce(nullif(trim(a['source_locator']),''),source||':witness['||cast(ordinal+1 AS VARCHAR)||']') AS source_locator,
  nullif(trim(a['name_key']),'') AS name_key,
  nullif(trim(a['name']),'') AS name,
  nullif(trim(a['honorific']),'') AS honorific,
  nullif(trim(a['given']),'') AS given,
  nullif(trim(a['middle']),'') AS middle,
  nullif(trim(a['family']),'') AS family,
  nullif(trim(a['suffix']),'') AS suffix,
  nullif(trim(a['position']),'') AS position,
  nullif(trim(a['organization']),'') AS organization,
  nullif(trim(a['on_behalf_of']),'') AS on_behalf_of,
  nullif(trim(a['location']),'') AS location,
  nullif(trim(a['panel']),'') AS panel,
  cast(a['panel_order'] AS SMALLINT) AS panel_order,
  cast(a['display_order'] AS SMALLINT) AS display_order,
  nullif(trim(a['witness_type']),'') AS witness_type,
  a['testified'] AS testified,
  nullif(trim(a['bioguide_id']),'') AS bioguide_id,
  a['document_links'] AS document_links
 FROM unnested_occurrences
), with_witness_key AS (
 SELECT
  substr(encode(sha256(json_array('witness-occurrence-v2',occasion,source,record_sha_hex,source_locator,context_key)),'hex'),1,16) AS witness_key,
  *
 FROM extracted_occurrences
), raw_link_rows AS (
 SELECT
  witness_key,
  resolved_base,
  unnest(document_links) AS raw_link,
  unnest(range(0,cast(array_length(document_links) AS BIGINT))) AS link_idx
 FROM with_witness_key
 WHERE document_links IS NOT NULL AND coalesce(array_length(document_links),0)>0
), resolved_link_rows AS (
 SELECT
  witness_key,
  link_idx,
  CASE
   WHEN resolved_base IS NOT NULL THEN url_resolve(trim(raw_link),resolved_base)
   WHEN regexp_like(trim(raw_link),'(?i)^https?://') THEN trim(raw_link)
  END AS resolved_url
 FROM raw_link_rows
 WHERE raw_link IS NOT NULL AND trim(raw_link)<>''
), aggregated_links AS (
 SELECT
  witness_key,
  array_agg(resolved_url ORDER BY link_idx) AS document_urls
 FROM resolved_link_rows
 WHERE resolved_url IS NOT NULL AND regexp_like(resolved_url,'(?i)^https?://')
 GROUP BY witness_key
)
SELECT
 w.witness_key,
 w.occasion,
 w.source,
 arrow_cast(decode(w.record_sha_hex,'hex'),'FixedSizeBinary(32)') AS record_sha,
 w.record_sha_hex,
 w.source_locator,
 w.context_key,
 w.event_id,
 w.package_id,
 w.page_url,
 w.name_key,
 w.name,
 w.honorific,
 w.given,
 w.middle,
 w.family,
 w.suffix,
 w.position,
 w.organization,
 w.on_behalf_of,
 w.location,
 w.panel,
 w.panel_order,
 w.display_order,
 w.witness_type,
 w.testified,
 w.bioguide_id,
 coalesce(al.document_urls,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS document_urls
FROM with_witness_key w
LEFT JOIN aggregated_links al ON w.witness_key=al.witness_key
