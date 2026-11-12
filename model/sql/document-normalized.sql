-- A merged recovered copy's link (x, recovered-copy-fills.sql) fills only a field the copy lacks.
-- Filename date, Congress and package come from every copy (fc, pk), never only the saved one (a);
-- printed hearing packages also inherit their GPO MODS date, committees, chambers and title fallback (cat2-x47u);
-- plausible filename dates lead, while suspect filename dates yield to valid content/meeting/MODS dates (cat2-8ai9).
-- The engine builds each hash join on its left input, so every outer join names its small relation
-- first and the document row streams past it; an outer join built on that row exhausted the pool (ct-n5ec).
SELECT q.doc_key,q.body_expected,q.filename,q.own_title,q.own_title_source,q.link_title,q.mods_title,q.component,
 q.document_kind,q.document_family,q.committee_keys,q.chambers,q.congress,q.format,
 coalesce(
  CASE WHEN q.fc_date IS NOT NULL
   AND (q.first_captured IS NULL OR q.fc_date<=q.first_captured+INTERVAL '30 days')
   AND (q.congress IS NULL OR date_part('year',q.fc_date) BETWEEN 2*cast(q.congress AS INT)+1786 AND 2*cast(q.congress AS INT)+1790)
   THEN q.fc_date END,
  q.content_date,q.meeting_date,q.mods_date,
  CASE WHEN q.x_date IS NOT NULL
   AND (q.first_captured IS NULL OR q.x_date<=q.first_captured+INTERVAL '30 days')
   AND (q.congress IS NULL OR date_part('year',q.x_date) BETWEEN 2*cast(q.congress AS INT)+1786 AND 2*cast(q.congress AS INT)+1790)
   THEN q.x_date END,
  q.fc_date,q.x_date
 ) AS document_date,
 q.first_captured,q.date_kind,q.saved_kind,q.hidden,
 q.meeting_keys,q.measure_keys,q.bioguide_ids,q.witness_keys,q.version_keys,
 q.body_hex,q.source_url,q.suffix,q.media_type,q.bytes,
 CASE
  WHEN q.fc_date IS NOT NULL
   AND (q.first_captured IS NULL OR q.fc_date<=q.first_captured+INTERVAL '30 days')
   AND (q.congress IS NULL OR date_part('year',q.fc_date) BETWEEN 2*cast(q.congress AS INT)+1786 AND 2*cast(q.congress AS INT)+1790)
   THEN 'filename'
  WHEN q.content_date IS NOT NULL THEN 'content'
  WHEN q.meeting_date IS NOT NULL THEN 'meeting'
  WHEN q.mods_date IS NOT NULL THEN 'content'
  WHEN q.x_date IS NOT NULL
   AND (q.first_captured IS NULL OR q.x_date<=q.first_captured+INTERVAL '30 days')
   AND (q.congress IS NULL OR date_part('year',q.x_date) BETWEEN 2*cast(q.congress AS INT)+1786 AND 2*cast(q.congress AS INT)+1790)
   THEN 'filename'
  WHEN q.fc_date IS NOT NULL THEN 'filename'
  WHEN q.x_date IS NOT NULL THEN 'filename'
 END AS document_date_source,
 q.in_archive_since,q.removed_on,q.review_note,q.review_decided_at,q.alternates,q.package_id,q.facts,q.link_bodies
FROM (
SELECT d.document_id AS doc_key,true AS body_expected,
 CASE WHEN coalesce(s.filename,'')='' THEN coalesce(x.filename,s.filename) ELSE s.filename END AS filename,
 -- Title evidence; titles.sql chooses the title.
 a.reading_title AS own_title,a.reading_source AS own_title_source,a.listing_title AS link_title,pmf.mods_title,d.component,
 CASE WHEN coalesce(array_length(a.document_kind),0)=0 THEN coalesce(x.document_kind,a.document_kind) ELSE a.document_kind END AS document_kind,
 CASE WHEN coalesce(array_length(a.document_family),0)=0 THEN coalesce(x.document_family,a.document_family) ELSE a.document_family END AS document_family,
 array_sort(array_distinct(array_concat(array_concat(m.committee_keys,coalesce(ml.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),coalesce(pmf.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))))) AS committee_keys,
 array_sort(array_distinct(array_concat(
  array_concat(array_concat(m.chambers,coalesce(ml.chambers,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),coalesce(pmf.chambers,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),
  array_except(make_array(
   CASE WHEN regexp_like(array_to_string(array_concat(array_concat(m.committee_keys,coalesce(ml.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),coalesce(pmf.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),','),'(?:^|,)h')
    OR regexp_like(coalesce(CASE WHEN NOT coalesce(pk.bill_package_conflict,false) AND NOT coalesce(bd.package_withheld,false) THEN coalesce(pk.package_id,x.package_id) END,''),'(?i)^CHRG-[0-9]{1,3}hhrg') THEN 'house' ELSE '' END,
   CASE WHEN regexp_like(array_to_string(array_concat(array_concat(m.committee_keys,coalesce(ml.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),coalesce(pmf.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),','),'(?:^|,)s')
    OR regexp_like(coalesce(CASE WHEN NOT coalesce(pk.bill_package_conflict,false) AND NOT coalesce(bd.package_withheld,false) THEN coalesce(pk.package_id,x.package_id) END,''),'(?i)^CHRG-[0-9]{1,3}shrg') THEN 'senate' ELSE '' END,
   CASE WHEN regexp_like(array_to_string(array_concat(array_concat(m.committee_keys,coalesce(ml.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),coalesce(pmf.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),','),'(?:^|,)j')
    OR regexp_like(coalesce(CASE WHEN NOT coalesce(pk.bill_package_conflict,false) AND NOT coalesce(bd.package_withheld,false) THEN coalesce(pk.package_id,x.package_id) END,''),'(?i)^CHRG-[0-9]{1,3}jhrg') THEN 'joint' ELSE '' END
  ),make_array(''))
 ))) AS chambers,
 cast(coalesce(
  fc.congress,x.congress,ml.congress,
  try_cast((regexp_match(coalesce(CASE WHEN NOT coalesce(pk.bill_package_conflict,false) AND NOT coalesce(bd.package_withheld,false) THEN coalesce(pk.package_id,x.package_id) END,''),'(?i)^(?:CHRG|CRPT|CPRT|CDOC|BILLS)-([1-9][0-9]{0,2})'))[1] AS INT)
 ) AS SMALLINT) AS congress,s.format,
 fc.filename_date AS fc_date,a.content_date,ml.meeting_date,pmf.mods_date,x.filename_date AS x_date,
 cast(m.first_fetched AS DATE) AS first_captured,
 CASE WHEN m.first_fetched IS NOT NULL THEN 'captured' WHEN m.in_archive_since IS NOT NULL THEN 'import_day' ELSE 'unknown' END AS date_kind,
 'original' AS saved_kind,false AS hidden,
 array_sort(array_distinct(array_concat(m.meeting_keys,coalesce(ml.meeting_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))))) AS meeting_keys,
 m.measure_keys,m.bioguide_ids,
 coalesce(wk.witness_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS witness_keys,
 coalesce(v.version_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS version_keys,
 s.body_sha AS body_hex,s.source_url,b.suffix,
 CASE s.format WHEN 'pdf' THEN 'application/pdf' WHEN 'html' THEN 'text/html' WHEN 'xml' THEN 'application/xml'
 WHEN 'json' THEN 'application/json' WHEN 'text' THEN 'text/plain' WHEN 'doc' THEN 'application/msword'
 WHEN 'docx' THEN 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
 WHEN 'zip' THEN 'application/zip' ELSE s.media_type END AS media_type,
 b.original_size AS bytes,
 m.in_archive_since,cast(NULL AS DATE) AS removed_on,cast(NULL AS VARCHAR) AS review_note,cast(NULL AS DATE) AS review_decided_at,
 coalesce(alt.alternates,array_slice(make_array(named_struct('format',cast(NULL AS VARCHAR),
 'body',arrow_cast(NULL,'FixedSizeBinary(32)'),'suffix',cast(NULL AS VARCHAR),'size',cast(NULL AS BIGINT))),1,0)) AS alternates,
 CASE WHEN NOT coalesce(pk.bill_package_conflict,false) AND NOT coalesce(bd.package_withheld,false) THEN coalesce(pk.package_id,x.package_id) END AS package_id,
 CASE WHEN coalesce(array_length(a.facts),0)=0 THEN coalesce(x.facts,a.facts) ELSE a.facts END AS facts,bodies.link_bodies
FROM (
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
) pmf RIGHT JOIN (
 document_bill_decisions bd RIGHT JOIN (
  document_filename_facts fc RIGHT JOIN (
   recovered_copy_fills x RIGHT JOIN (
     document_witness_keys wk RIGHT JOIN (
      component_meeting_links ml RIGHT JOIN (
       document_versions v RIGHT JOIN (
        document_alternates alt RIGHT JOIN (
         document_packages pk RIGHT JOIN (
          document_bodies bodies JOIN (
           body_evidence b JOIN (
            document_metadata m JOIN (
             document_identities d JOIN saved_files s ON d.component=s.component AND s.saved_rank=1
             JOIN source_annotations a ON s.source_id=a.source_id
            ) ON d.component=m.component
           ) ON s.body_sha=b.body_sha
          ) ON d.component=bodies.component
         ) ON d.component=pk.component
        ) ON d.component=alt.component
       ) ON d.component=v.component
      ) ON d.component=ml.component
     ) ON d.component=wk.component
   ) ON d.component=x.component
  ) ON d.component=fc.component
 ) ON d.component=bd.component
) ON pmf.pmf_package_id=CASE WHEN NOT coalesce(pk.bill_package_conflict,false) AND NOT coalesce(bd.package_withheld,false) THEN coalesce(pk.package_id,x.package_id) END
) q
