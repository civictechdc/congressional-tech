SELECT document_id AS legacy_document_id,filename,source_url,body_key,
 body_keys AS declared_body_keys,
 array_element(source_link_label,1) AS title,
 lower(array_element(format,1)) AS format,
 array_element(media_type,1) AS media_type,
 document_kind,document_family,committee_code,
 CASE WHEN cardinality(congress)=1 THEN try_cast(congress[1] AS SMALLINT) END AS congress,
 CASE WHEN cardinality(date_token)=1 THEN try_cast(CASE
 WHEN regexp_like(date_token[1],'^[0-9]{8}$') THEN substr(date_token[1],1,4)||'-'||substr(date_token[1],5,2)||'-'||substr(date_token[1],7,2)
 ELSE date_token[1] END AS DATE) END AS document_date,
 measure_references,member_bioguide_id,hearing_package_id,
 source_meeting_id,source_meeting_title,source_meeting_date,source_chamber,
 source_committee_code,source_committee_name,array_element(source_page_url,1) AS source_page
FROM v5_documents
