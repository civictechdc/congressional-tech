SELECT d.document_id AS doc_key,false AS body_expected,n.filename,cast(NULL AS VARCHAR) AS title,
 a.document_kind,a.document_family,a.committee_keys,a.chambers,cast(a.congress AS SMALLINT) AS congress,
 coalesce(b.format,'other') AS format,a.filename_date AS document_date,cast(NULL AS DATE) AS first_captured,
 'import_day' AS date_kind,'recovery' AS saved_kind,false AS hidden,a.meeting_keys,a.measure_keys,a.bioguide_ids,
 arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS witness_keys,
 arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS version_keys,
 r.body_sha AS body_hex,r.original_url AS source_url,b.suffix,
 coalesce(c.media_type,'application/octet-stream') AS media_type,r.bytes AS bytes,
 CASE WHEN a.filename_date IS NOT NULL THEN 'filename' END AS document_date_source,
 cast(r.imported_at AS DATE) AS in_archive_since,cast(NULL AS DATE) AS removed_on,
 cast(NULL AS VARCHAR) AS review_note,cast(NULL AS DATE) AS review_decided_at,
 array_slice(make_array(named_struct('format',cast(NULL AS VARCHAR),'body',arrow_cast(NULL,'FixedSizeBinary(32)'),
 'suffix',cast(NULL AS VARCHAR),'size',cast(NULL AS BIGINT))),1,0) AS alternates,
 a.package_id,a.facts,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS link_bodies
FROM document_identities d JOIN saved_recoveries r ON d.component=r.component AND r.saved_rank=1
JOIN effective_filenames n ON n.input_id='recovery:'||r.id
JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
JOIN source_annotations a ON f.source_id=a.source_id
JOIN body_evidence b ON r.body_sha=b.body_sha
LEFT JOIN (SELECT encode(sha256,'hex') AS body_sha,max(media_type) AS media_type FROM captures GROUP BY sha256) c ON r.body_sha=c.body_sha
WHERE NOT d.has_real
