-- A merged recovered copy's link (x, recovered-copy-fills.sql) fills only a field the copy lacks.
-- Filename date, Congress and package come from every copy (fc, pk), never only the saved one (a);
-- printed hearing packages also inherit their GPO MODS date, committees, chambers and title fallback (cat2-x47u).
-- The engine builds each hash join on its left input, so every outer join names its small relation
-- first and the document row streams past it; an outer join built on that row exhausted the pool (ct-n5ec).
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
  try_cast((regexp_match(coalesce(CASE WHEN NOT coalesce(pk.bill_package_conflict,false) AND NOT coalesce(bd.package_withheld,false) THEN coalesce(pk.package_id,x.package_id) END,''),'(?i)^(?:CHRG|CRPT|CPRT|CDOC|BILLS)-([1-9][0-9]{0,2})'))[1] AS INT),
  CASE
   WHEN coalesce(fc.filename_date,a.content_date,ml.meeting_date,pmf.mods_date,x.filename_date)>=DATE '1789-03-04'
    AND date_part('year',coalesce(fc.filename_date,a.content_date,ml.meeting_date,pmf.mods_date,x.filename_date))<=2028
    AND NOT (
     (fc.filename_date IS NOT NULL OR (a.content_date IS NULL AND ml.meeting_date IS NULL AND pmf.mods_date IS NULL AND x.filename_date IS NOT NULL))
     AND m.first_fetched IS NOT NULL
     AND coalesce(fc.filename_date,a.content_date,ml.meeting_date,pmf.mods_date,x.filename_date)>cast(m.first_fetched AS DATE)+INTERVAL '30 days'
    )
   THEN (cast(date_part('year',coalesce(fc.filename_date,a.content_date,ml.meeting_date,pmf.mods_date,x.filename_date)) AS INT)
    -CASE WHEN substr(cast(coalesce(fc.filename_date,a.content_date,ml.meeting_date,pmf.mods_date,x.filename_date) AS VARCHAR),6,5)<'01-03' THEN 1 ELSE 0 END-1789)/2+1
  END
 ) AS SMALLINT) AS congress,s.format,
 coalesce(fc.filename_date,a.content_date,ml.meeting_date,pmf.mods_date,x.filename_date) AS document_date,cast(m.first_fetched AS DATE) AS first_captured,
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
 CASE WHEN fc.filename_date IS NOT NULL THEN 'filename' WHEN a.content_date IS NOT NULL THEN 'content' WHEN ml.meeting_date IS NOT NULL THEN 'meeting'
 WHEN pmf.mods_date IS NOT NULL THEN 'content' WHEN x.filename_date IS NOT NULL THEN 'filename' END AS document_date_source,
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
