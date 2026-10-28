SELECT d.document_id AS legacy_document_id,coalesce(nullif(d.filename,''),u.filename,b.filename) AS filename,d.source_url,d.body_key,
 d.filename AS raw_filename,array_element(d.format,1) AS raw_format,
 CASE WHEN d.filename IS NULL OR d.filename='' THEN coalesce(u.candidates,b.candidates,0) ELSE 0 END AS filename_candidates,
 coalesce(f.candidates,0) AS byte_format_candidates,
 body_keys AS declared_body_keys,
 array_element(source_link_label,1) AS title,
 lower(coalesce(nullif(array_element(d.format,1),''),f.format)) AS format,
 array_element(media_type,1) AS media_type,
 document_kind,document_family,committee_code,
 CASE WHEN cardinality(congress)=1 THEN try_cast(congress[1] AS SMALLINT) END AS congress,
 CASE WHEN cardinality(date_token)=1 THEN try_cast(CASE
 WHEN regexp_like(date_token[1],'^[0-9]{8}$') THEN substr(date_token[1],1,4)||'-'||substr(date_token[1],5,2)||'-'||substr(date_token[1],7,2)
 ELSE date_token[1] END AS DATE) END AS document_date,
 measure_references,member_bioguide_id,hearing_package_id,
 source_meeting_id,source_meeting_title,source_meeting_date,source_chamber,
 source_committee_code,source_committee_name,array_element(source_page_url,1) AS source_page
FROM v5_documents d
LEFT JOIN seed_name_url u ON d.body_key=u.body_key AND d.source_url IS NOT NULL AND d.source_url=u.source_url
LEFT JOIN seed_name_body b ON d.body_key=b.body_key
LEFT JOIN seed_body_formats f ON d.body_key=f.body_key
