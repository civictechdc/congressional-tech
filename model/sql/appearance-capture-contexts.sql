-- Narrow candidate capture facts, materialized once for context binding, retained-file event IDs,
-- and observation eligibility. A reviewed exclusion follows its receipt context, never its bytes.
WITH candidate_appearance_shas AS (
 SELECT DISTINCT arrow_cast(decode(record_sha_hex,'hex'),'FixedSizeBinary(32)') AS sha256
 FROM selected_appearance_records WHERE record_sha_hex IS NOT NULL
), classified AS (
 SELECT c.*,
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
  encode(c.sha256,'hex') AS record_sha_hex
 FROM candidate_appearance_shas cas
 JOIN captures c ON c.sha256=cas.sha256
)
SELECT c.record_sha_hex,c.source,c.mode,c.complete,c.outcome,c.http_status,
 coalesce(c.url,c.requested_url,c.context_url) AS source_url,c.member_path,c.retrieved_at,
 c.original_path,c.receipt_key,c.receipt_line,c.capture_index,c.run_id,
 e.reason AS exclusion_reason,
 coalesce(c.mode='fetch' AND c.outcome IN ('stored','unchanged') AND (
  (c.complete AND c.http_status BETWEEN 200 AND 299)
  OR (c.fidelity='retained-file' AND nullif(trim(c.original_path),'') IS NOT NULL)
 ),false) AS source_qualified
FROM appearance_observation_exclusions e
RIGHT JOIN classified c
 ON c.source=e.source AND c.receipt_key=e.receipt_key AND c.receipt_line=e.receipt_line
 AND c.capture_index=e.capture_index AND c.run_id=e.run_id
