SELECT d.document_id AS doc_key,false AS body_expected,n.filename,
 t.title AS own_title,t.source AS own_title_source,a.listing_title AS link_title,pmf.mods_title,d.component,
 a.document_kind,a.document_family,
 array_sort(array_distinct(array_concat(array_concat(a.committee_keys,coalesce(ml.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),coalesce(pmf.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))))) AS committee_keys,
 array_sort(array_distinct(array_concat(
  array_concat(array_concat(a.chambers,coalesce(ml.chambers,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),coalesce(pmf.chambers,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),
  array_except(make_array(
   CASE WHEN regexp_like(array_to_string(array_concat(array_concat(a.committee_keys,coalesce(ml.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),coalesce(pmf.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),','),'(?:^|,)h')
    OR regexp_like(coalesce(a.package_id,''),'(?i)^CHRG-[0-9]{1,3}hhrg') THEN 'house' ELSE '' END,
   CASE WHEN regexp_like(array_to_string(array_concat(array_concat(a.committee_keys,coalesce(ml.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),coalesce(pmf.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),','),'(?:^|,)s')
    OR regexp_like(coalesce(a.package_id,''),'(?i)^CHRG-[0-9]{1,3}shrg') THEN 'senate' ELSE '' END,
   CASE WHEN regexp_like(array_to_string(array_concat(array_concat(a.committee_keys,coalesce(ml.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),coalesce(pmf.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),','),'(?:^|,)j')
    OR regexp_like(coalesce(a.package_id,''),'(?i)^CHRG-[0-9]{1,3}jhrg') THEN 'joint' ELSE '' END
  ),make_array(''))
 ))) AS chambers,
 cast(coalesce(
  a.congress,ml.congress,
  try_cast((regexp_match(coalesce(a.package_id,''),'(?i)^(?:CHRG|CRPT|CPRT|CDOC|BILLS)-([1-9][0-9]{0,2})'))[1] AS INT),
  CASE
   WHEN coalesce(a.filename_date,ml.meeting_date,pmf.mods_date)>=DATE '1789-03-04'
    AND date_part('year',coalesce(a.filename_date,ml.meeting_date,pmf.mods_date))<=2028
   THEN (cast(date_part('year',coalesce(a.filename_date,ml.meeting_date,pmf.mods_date)) AS INT)
    -CASE WHEN substr(cast(coalesce(a.filename_date,ml.meeting_date,pmf.mods_date) AS VARCHAR),6,5)<'01-03' THEN 1 ELSE 0 END-1789)/2+1
  END
 ) AS SMALLINT) AS congress,
 coalesce(b.format,'other') AS format,coalesce(a.filename_date,ml.meeting_date,pmf.mods_date) AS document_date,cast(NULL AS DATE) AS first_captured,
 'import_day' AS date_kind,'recovery' AS saved_kind,false AS hidden,
 array_sort(array_distinct(array_concat(a.meeting_keys,coalesce(ml.meeting_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))))) AS meeting_keys,
 a.measure_keys,a.bioguide_ids,
 coalesce(wk.witness_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS witness_keys,
 arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS version_keys,
 r.body_sha AS body_hex,r.original_url AS source_url,b.suffix,
 coalesce(c.media_type,'application/octet-stream') AS media_type,r.bytes AS bytes,
 CASE WHEN a.filename_date IS NOT NULL THEN 'filename' WHEN ml.meeting_date IS NOT NULL THEN 'meeting' WHEN pmf.mods_date IS NOT NULL THEN 'content' END AS document_date_source,
 cast(r.imported_at AS DATE) AS in_archive_since,cast(NULL AS DATE) AS removed_on,
 cast(NULL AS VARCHAR) AS review_note,cast(NULL AS DATE) AS review_decided_at,
 array_slice(make_array(named_struct('format',cast(NULL AS VARCHAR),'body',arrow_cast(NULL,'FixedSizeBinary(32)'),
 'suffix',cast(NULL AS VARCHAR),'size',cast(NULL AS BIGINT))),1,0) AS alternates,
 a.package_id,a.facts,
 -- An edition on a document of its own (ct-u9y4) is found by its body key; any other recovery-only row by its link.
 CASE WHEN r.role='edition' THEN arrow_cast(make_array(r.body_sha),'List(Utf8)')
  ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') END AS link_bodies
FROM saved_recoveries r JOIN document_identities d ON d.component=r.component AND r.saved_rank=1
JOIN effective_filenames n ON n.input_id='recovery:'||r.id
-- The original address has no body, so its annotation's only title is its link text.
JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
JOIN source_annotations a ON f.source_id=a.source_id
JOIN body_evidence b ON r.body_sha=b.body_sha
-- Only the saved recovered bodies are read from captures and page_facts (candidate semi-join);
-- the candidate set comes first so the join builds on it, not on captures.
LEFT JOIN (SELECT encode(c.sha256,'hex') AS body_sha,max(c.media_type) AS media_type
 FROM (SELECT DISTINCT decode(body_sha,'hex') AS sha256 FROM saved_recoveries WHERE saved_rank=1) s JOIN captures c ON c.sha256=s.sha256 GROUP BY c.sha256) c ON r.body_sha=c.body_sha
-- A document that showed its dead page keeps the page's title on the file (ct-u9y4; owner, 2026-11-11), not the
-- hearing record's own title nor none: the title is read from the page the document showed, else the saved file.
LEFT JOIN (SELECT encode(p.body_sha,'hex') AS body_sha,
 CASE
  WHEN nullif(trim(max(p.heading)),'') IS NOT NULL AND (
   nullif(trim(max(p.title)),'') IS NULL
   OR (
    NOT regexp_like(trim(max(p.heading)),'(?i)^(?:(?:(?:the\s+)?(?:united\s+states|u\.?s\.?)\s+)?(?:senate|house(?:\s+of\s+representatives)?)\s+)?(?:(?:committee|subcommittee|select\s+committee|special\s+committee|joint\s+committee)\s+on\s+[^|–—-]+|hearings?|events?|news|press\s+releases?|home|committee\s+hearings?|calendar|business\s+meetings?|markups?|roundtables?|search)$')
    AND (
     regexp_like(trim(max(p.title)),'(?i)^(?:hearings?|events?|news|press\s+releases?|home|committee\s+hearings?|calendar|business\s+meetings?|markups?)\s*[|–—-]')
     OR (length(trim(max(p.heading)))>length(trim(max(p.title))) AND regexp_like(trim(max(p.title)),'(?i)^(?:(?:the\s+)?(?:united\s+states|u\.?s\.?)\s+)?(?:senate|house(?:\s+of\s+representatives)?)\s+(?:(?:select|special|permanent\s+select|joint)\s+)?committee\s+on\s+[^|:]+$'))
     OR (length(trim(max(p.heading)))>=12 AND regexp_like(trim(max(p.title)),'(?:\.\.\.|…)\s*(?:\||$)'))
    )
   )
  ) THEN trim(max(p.heading))
  ELSE nullif(trim(max(p.title)),'')
 END AS title,
 CASE
  WHEN nullif(trim(max(p.heading)),'') IS NOT NULL AND (
   nullif(trim(max(p.title)),'') IS NULL
   OR (
    NOT regexp_like(trim(max(p.heading)),'(?i)^(?:(?:(?:the\s+)?(?:united\s+states|u\.?s\.?)\s+)?(?:senate|house(?:\s+of\s+representatives)?)\s+)?(?:(?:committee|subcommittee|select\s+committee|special\s+committee|joint\s+committee)\s+on\s+[^|–—-]+|hearings?|events?|news|press\s+releases?|home|committee\s+hearings?|calendar|business\s+meetings?|markups?|roundtables?|search)$')
    AND (
     regexp_like(trim(max(p.title)),'(?i)^(?:hearings?|events?|news|press\s+releases?|home|committee\s+hearings?|calendar|business\s+meetings?|markups?)\s*[|–—-]')
     OR (length(trim(max(p.heading)))>length(trim(max(p.title))) AND regexp_like(trim(max(p.title)),'(?i)^(?:(?:the\s+)?(?:united\s+states|u\.?s\.?)\s+)?(?:senate|house(?:\s+of\s+representatives)?)\s+(?:(?:select|special|permanent\s+select|joint)\s+)?committee\s+on\s+[^|:]+$'))
     OR (length(trim(max(p.heading)))>=12 AND regexp_like(trim(max(p.title)),'(?:\.\.\.|…)\s*(?:\||$)'))
    )
   )
  ) THEN 'page_heading'
  WHEN nullif(trim(max(p.title)),'') IS NOT NULL THEN 'page_title'
 END AS source
 FROM (SELECT DISTINCT decode(coalesce(page_shown,body_sha),'hex') AS sha256 FROM saved_recoveries WHERE saved_rank=1) s JOIN source_annotation_pages p ON p.body_sha=s.sha256 WHERE p.status='completed' GROUP BY p.body_sha) t ON coalesce(r.page_shown,r.body_sha)=t.body_sha
LEFT JOIN component_meeting_links ml ON d.component=ml.component
LEFT JOIN document_witness_keys wk ON d.component=wk.component
LEFT JOIN (
 SELECT p.package_id AS pmf_package_id,
  CASE WHEN cardinality(p.held_dates)=1 THEN try_cast(p.held_dates[1] AS DATE) END AS mods_date,
  nullif(trim(regexp_replace(p.title,'^\s*[-–—]+\s+','')),'') AS mods_title,
  mc.committee_keys,mc.chambers
 FROM (
  SELECT m.package_id,
   array_sort(array_distinct(array_agg(c.system_code))) AS committee_keys,
   array_sort(array_distinct(array_agg(c.chamber))) AS chambers
  FROM (SELECT package_id,upper(trim(unnest(committees))) AS code FROM package_mods_facts WHERE coalesce(cardinality(committees),0)>0) m
  JOIN committee_codes c ON c.code=m.code
  GROUP BY m.package_id
 ) mc
 RIGHT JOIN package_mods_facts p ON mc.package_id=p.package_id
) pmf ON pmf.pmf_package_id=a.package_id
WHERE NOT d.has_real
