SELECT d.document_id AS doc_key,true AS body_expected,s.filename,a.title,
 a.document_kind,a.document_family,m.committee_keys,m.chambers,cast(a.congress AS SMALLINT) AS congress,s.format,
 coalesce(a.filename_date,a.content_date) AS document_date,cast(m.first_fetched AS DATE) AS first_captured,
 CASE WHEN m.first_fetched IS NOT NULL THEN 'captured' ELSE 'unknown' END AS date_kind,
 'original' AS saved_kind,false AS hidden,m.meeting_keys,m.measure_keys,m.bioguide_ids,
 arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS witness_keys,
 coalesce(v.version_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS version_keys,
 s.body_sha AS body_hex,s.source_url,b.suffix,
 CASE s.format WHEN 'pdf' THEN 'application/pdf' WHEN 'html' THEN 'text/html' WHEN 'xml' THEN 'application/xml'
 WHEN 'json' THEN 'application/json' WHEN 'text' THEN 'text/plain' WHEN 'doc' THEN 'application/msword'
 WHEN 'docx' THEN 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
 WHEN 'zip' THEN 'application/zip' ELSE c.media_type END AS media_type,
 b.stored_size AS bytes,
 CASE WHEN a.filename_date IS NOT NULL THEN 'filename' WHEN a.content_date IS NOT NULL THEN 'content' END AS document_date_source,
 m.in_archive_since,cast(NULL AS DATE) AS removed_on,cast(NULL AS VARCHAR) AS review_note,cast(NULL AS DATE) AS review_decided_at,
 coalesce(alt.alternates,array_slice(make_array(named_struct('format',cast(NULL AS VARCHAR),
 'body',arrow_cast(NULL,'FixedSizeBinary(32)'),'suffix',cast(NULL AS VARCHAR),'size',cast(NULL AS BIGINT))),1,0)) AS alternates,
 a.package_id,a.facts,bodies.link_bodies
FROM document_identities d JOIN saved_files s ON d.component=s.component AND s.saved_rank=1
JOIN source_annotations a ON s.source_id=a.source_id JOIN document_metadata m ON d.component=m.component
JOIN body_evidence b ON s.body_sha=b.body_sha JOIN document_bodies bodies ON d.component=bodies.component
LEFT JOIN document_alternates alt ON d.component=alt.component LEFT JOIN document_versions v ON d.component=v.component
LEFT JOIN (SELECT source_id,max(media_type) AS media_type FROM capture_sources GROUP BY source_id) c ON s.source_id=c.source_id
