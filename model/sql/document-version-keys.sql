SELECT e.source_id,substr(encode(sha256(json_array(e.endpoint_key,e.member_path)),'hex'),1,16) AS version_key
FROM (SELECT * FROM ambiguous_endpoints WHERE endpoint_key IS NOT NULL) a JOIN endpoint_bodies e
 ON (e.endpoint_key IS NOT DISTINCT FROM a.endpoint_key) AND (e.member_path IS NOT DISTINCT FROM a.member_path)
