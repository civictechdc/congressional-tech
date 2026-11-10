-- A merged recovered copy's link (x, recovered-copy-fills.sql) fills only a field the copy lacks.
-- Filename date, Congress and package come from every copy (fc, pk), never only the saved one (a).
-- The engine builds each hash join on its left input, so every outer join names its small relation
-- first and the document row streams past it; an outer join built on that row exhausted the pool (ct-n5ec).
SELECT d.document_id AS doc_key,true AS body_expected,
 CASE WHEN coalesce(s.filename,'')='' THEN coalesce(x.filename,s.filename) ELSE s.filename END AS filename,
 CASE
  WHEN wk.witness_name IS NOT NULL THEN coalesce(
   CASE WHEN NOT regexp_like(trim(a.reading_title),'(?i)^(?:witness\s+(?:statement|testimony|biography)|(?:prepared|written)\s+statement|testimony|truth\s+in\s+testimony(?:\s+form|\s+disclosure(?:\s+form)?)?)$') THEN a.reading_title END,
   CASE WHEN NOT regexp_like(trim(a.listing_title),'(?i)^(?:witness\s+(?:statement|testimony|biography)|(?:prepared|written)\s+statement|testimony|truth\s+in\s+testimony(?:\s+form|\s+disclosure(?:\s+form)?)?)$') THEN a.listing_title END,
   CASE WHEN NOT regexp_like(trim(rt.title),'(?i)^(?:witness\s+(?:statement|testimony|biography)|(?:prepared|written)\s+statement|testimony|truth\s+in\s+testimony(?:\s+form|\s+disclosure(?:\s+form)?)?)$') THEN rt.title END,
   CASE WHEN NOT regexp_like(trim(x.title),'(?i)^(?:witness\s+(?:statement|testimony|biography)|(?:prepared|written)\s+statement|testimony|truth\s+in\s+testimony(?:\s+form|\s+disclosure(?:\s+form)?)?)$') THEN x.title END,
   CASE WHEN coalesce(a.reading_title,a.listing_title,rt.title,x.title) IS NOT NULL THEN coalesce(a.reading_title,a.listing_title,rt.title,x.title)||' - '||wk.witness_name END
  )
  ELSE coalesce(a.reading_title,a.listing_title,rt.title,x.title)
 END AS title,
 CASE WHEN coalesce(array_length(a.document_kind),0)=0 THEN coalesce(x.document_kind,a.document_kind) ELSE a.document_kind END AS document_kind,
 CASE WHEN coalesce(array_length(a.document_family),0)=0 THEN coalesce(x.document_family,a.document_family) ELSE a.document_family END AS document_family,
 array_sort(array_distinct(array_concat(m.committee_keys,coalesce(ml.committee_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))))) AS committee_keys,
 array_sort(array_distinct(array_concat(m.chambers,coalesce(ml.chambers,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))))) AS chambers,
 cast(coalesce(fc.congress,x.congress,ml.congress) AS SMALLINT) AS congress,s.format,
 coalesce(fc.filename_date,a.content_date,ml.meeting_date,x.filename_date) AS document_date,cast(m.first_fetched AS DATE) AS first_captured,
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
 WHEN x.filename_date IS NOT NULL THEN 'filename' END AS document_date_source,
 m.in_archive_since,cast(NULL AS DATE) AS removed_on,cast(NULL AS VARCHAR) AS review_note,cast(NULL AS DATE) AS review_decided_at,
 coalesce(alt.alternates,array_slice(make_array(named_struct('format',cast(NULL AS VARCHAR),
 'body',arrow_cast(NULL,'FixedSizeBinary(32)'),'suffix',cast(NULL AS VARCHAR),'size',cast(NULL AS BIGINT))),1,0)) AS alternates,
 CASE WHEN NOT coalesce(pk.bill_package_conflict,false) AND NOT coalesce(bd.package_withheld,false) THEN coalesce(pk.package_id,x.package_id) END AS package_id,
 CASE WHEN coalesce(array_length(a.facts),0)=0 THEN coalesce(x.facts,a.facts) ELSE a.facts END AS facts,bodies.link_bodies
FROM document_bill_decisions bd RIGHT JOIN (
 document_filename_facts fc RIGHT JOIN (
  recovered_copy_fills x RIGHT JOIN (
   document_rendition_titles rt RIGHT JOIN (
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
   ) ON d.component=rt.component
  ) ON d.component=x.component
 ) ON d.component=fc.component
) ON d.component=bd.component
