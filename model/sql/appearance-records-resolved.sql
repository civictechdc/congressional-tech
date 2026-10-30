WITH fetch_times AS (
 SELECT encode(sha256,'hex') AS record_sha_hex,
  max(arrow_cast(cast(retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS retrieved_at
 FROM captures
 WHERE sha256 IS NOT NULL AND mode='fetch' AND complete AND outcome IN ('stored','unchanged') AND http_status BETWEEN 200 AND 299
 GROUP BY sha256
), meeting_updates AS (
 SELECT record_sha_hex,
  max(arrow_cast(try_cast(m['updated'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS updated
 FROM (
  SELECT record_sha_hex,unnest(meetings) AS m
  FROM meeting_records_input WHERE status='completed' AND meetings IS NOT NULL
 ) GROUP BY record_sha_hex
), single_package_meetings AS (
 SELECT package_id,min(event_id) AS event_id
 FROM meeting_transcript_links
 GROUP BY package_id HAVING count(DISTINCT event_id)=1
), unnested AS (
 SELECT r.record_sha_hex,r.source,ms.priority,u.updated,f.retrieved_at,
  unnest(r.appearances) AS a,
  unnest(range(0,cast(array_length(r.appearances) AS BIGINT))) AS ordinal
 FROM appearance_records_input r
 JOIN meeting_sources ms ON ms.kind='appearance' AND r.source=ms.source
 LEFT JOIN meeting_updates u ON r.record_sha_hex=u.record_sha_hex
 LEFT JOIN fetch_times f ON r.record_sha_hex=f.record_sha_hex
 WHERE r.status='completed' AND r.appearances IS NOT NULL
), expanded AS (
 SELECT record_sha_hex,source,priority,updated,retrieved_at,ordinal,
  try_cast(a['event_id'] AS BIGINT) AS raw_event_id,
  nullif(trim(a['package_id']),'') AS package_id,
  nullif(trim(a['page_url']),'') AS page_url,
  nullif(trim(a['name_key']),'') AS name_key,
  nullif(trim(a['name']),'') AS name,
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
  a['document_urls'] AS document_urls
 FROM unnested
), with_occasion AS (
 SELECT e.record_sha_hex,e.source,e.priority,e.updated,e.retrieved_at,e.ordinal,
  CASE
   WHEN e.source IN ('house_xml','congress_gov') AND e.raw_event_id IS NOT NULL
    THEN 'meeting:'||cast(e.raw_event_id AS VARCHAR)
   WHEN e.source='mods' AND spm.event_id IS NOT NULL
    THEN 'meeting:'||cast(spm.event_id AS VARCHAR)
   WHEN e.source='mods' AND e.package_id IS NOT NULL
    THEN 'package:'||e.package_id
   WHEN e.source='senate_page' AND pk.url_key IS NOT NULL
    THEN 'page:'||substr(encode(sha256(pk.url_key),'hex'),1,16)
  END AS occasion,
  CASE
   WHEN e.source IN ('house_xml','congress_gov') THEN e.raw_event_id
   WHEN e.source='mods' THEN spm.event_id
   ELSE e.raw_event_id
  END AS event_id,
  e.package_id,e.page_url,e.name_key,e.name,e.position,e.organization,
  e.on_behalf_of,e.location,e.panel,e.panel_order,e.display_order,
  e.witness_type,e.testified,e.bioguide_id,e.document_urls
 FROM expanded e
 LEFT JOIN single_package_meetings spm ON e.source='mods' AND e.package_id=spm.package_id
 LEFT JOIN appearance_url_keys pk ON e.source='senate_page' AND e.page_url=pk.url AND pk.error IS NULL
), valid_rows AS (
 SELECT * FROM with_occasion WHERE occasion IS NOT NULL AND name_key IS NOT NULL
), dedup_within_record AS (
 SELECT *,row_number() OVER(
  PARTITION BY record_sha_hex,occasion,name_key
  ORDER BY ordinal ASC
 ) AS name_rn FROM valid_rows
), occasion_records AS (
 SELECT DISTINCT occasion,source,priority,record_sha_hex,updated,retrieved_at
 FROM dedup_within_record WHERE name_rn=1
), winning_records AS (
 SELECT *,row_number() OVER(
  PARTITION BY occasion
  ORDER BY priority ASC,updated DESC NULLS LAST,retrieved_at DESC NULLS LAST,record_sha_hex ASC
 ) AS rec_rn FROM occasion_records
)
SELECT
 substr(encode(sha256(json_array('witness',d.occasion,d.name_key)),'hex'),1,16) AS witness_key,
 d.occasion,d.event_id,d.package_id,d.page_url,d.name_key,d.name,d.position,
 d.organization,d.on_behalf_of,d.location,d.panel,d.panel_order,d.display_order,
 d.witness_type,d.testified,d.bioguide_id,d.source,d.document_urls
FROM dedup_within_record d
JOIN winning_records w ON d.occasion=w.occasion AND d.source=w.source AND d.record_sha_hex=w.record_sha_hex
WHERE d.name_rn=1 AND w.rec_rn=1
