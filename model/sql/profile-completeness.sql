-- Lake PKs and the actual producer work lists, never old derived decisions.
WITH expected_parsers AS (
 SELECT unnest(make_array('sniff','html','xml','json')) AS parser
), valid_admissions AS (
 SELECT body_sha FROM body_admissions
 WHERE format IN ('empty','vtt','m3u8') AND basis IS NOT NULL AND basis<>''
), missing_sniff AS (
 SELECT b.body_sha FROM profile_bodies b
 WHERE NOT EXISTS (SELECT 1 FROM sniff_facts f WHERE f.body_sha=b.body_sha)
 AND NOT EXISTS (SELECT 1 FROM valid_admissions a WHERE a.body_sha=b.body_sha)
 AND NOT EXISTS (SELECT 1 FROM readings r JOIN parser_versions v ON r.parser=v.parser AND r.parser_version=v.version
   WHERE r.body_sha=b.body_sha AND r.parser='sniff' AND r.status IN ('completed','error','size_limit'))
 AND NOT EXISTS (SELECT 1 FROM active_unreadable u WHERE u.body_sha256=encode(b.body_sha,'hex')
   AND ((u.parser='sniff' AND EXISTS (SELECT 1 FROM parser_versions v WHERE v.parser='sniff' AND v.version=u.parser_version))
     OR (u.parser='readings' AND u.parser_version={{READINGS_VERSION}})))
), missing_pages AS (
 SELECT DISTINCT b.body_sha,s.format FROM profile_bodies b JOIN sniff_facts s ON b.body_sha=s.body_sha
 JOIN parser_versions v ON s.format=v.parser WHERE s.format IN ('html','xml','json')
 AND NOT EXISTS (SELECT 1 FROM readings r WHERE r.body_sha=b.body_sha AND r.parser=v.parser
   AND r.parser_version=v.version AND r.status IN ('completed','error','size_limit'))
 AND NOT EXISTS (SELECT 1 FROM active_unreadable u WHERE u.body_sha256=encode(b.body_sha,'hex')
   AND ((u.parser=v.parser AND u.parser_version=v.version)
     OR (u.parser='readings' AND u.parser_version={{READINGS_VERSION}})))
), missing_filenames AS (
 SELECT p.* FROM profile_filename_pairs p WHERE NOT EXISTS (SELECT 1 FROM filename_readings f
   WHERE f.filename=p.filename AND f.source_url=p.source_url AND f.catalog_version={{CATALOG_VERSION}}
   AND f.status IN ('completed','error','size_limit'))
 AND NOT EXISTS (SELECT 1 FROM active_unreadable u WHERE u.parser='filename'
   AND u.parser_version={{CATALOG_VERSION}} AND u.record_sha=encode(sha256(json_array(p.filename,p.source_url)),'hex'))
)
SELECT
 (SELECT count(*) FROM (SELECT receipt_key,receipt_line,capture_index FROM captures
   GROUP BY receipt_key,receipt_line,capture_index HAVING count(*)>1)) AS duplicate_captures,
 (SELECT count(*) FROM (SELECT body_sha,parser,parser_version FROM readings
   GROUP BY body_sha,parser,parser_version HAVING count(*)>1)) AS duplicate_readings,
 (SELECT count(*) FROM (SELECT filename,source_url,catalog_version FROM filename_readings
   GROUP BY filename,source_url,catalog_version HAVING count(*)>1)) AS duplicate_filename_readings,
 (SELECT count(*) FROM (SELECT parser FROM parser_versions GROUP BY parser HAVING count(*)>1)) AS duplicate_parser_versions,
 (SELECT count(*) FROM captures WHERE receipt_key IS NULL OR receipt_line IS NULL OR capture_index IS NULL) AS invalid_capture_keys,
 (SELECT count(*) FROM readings WHERE body_sha IS NULL OR parser IS NULL OR parser_version IS NULL
   OR status IS NULL OR status NOT IN ('completed','error','size_limit')) AS invalid_readings,
 (SELECT count(*) FROM filename_readings WHERE filename IS NULL OR source_url IS NULL OR catalog_version IS NULL
   OR status IS NULL OR status NOT IN ('completed','error','size_limit')) AS invalid_filename_readings,
 (SELECT count(*) FROM parser_versions WHERE parser IS NULL OR version IS NULL OR version='') AS invalid_parser_versions,
 (SELECT count(*) FROM expected_parsers p WHERE NOT EXISTS (SELECT 1 FROM parser_versions v WHERE p.parser=v.parser)) AS missing_parser_versions,
 (SELECT count(*) FROM body_admissions WHERE body_sha IS NULL OR format IS NULL OR format NOT IN ('empty','vtt','m3u8')
   OR basis IS NULL OR basis='') AS invalid_body_admissions,
 (SELECT count(*) FROM missing_sniff) AS missing_sniff,
 (SELECT count(*) FROM missing_pages) AS missing_pages,
 (SELECT count(*) FROM missing_filenames) AS missing_filenames
