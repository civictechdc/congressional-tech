SELECT e.source_id,substr(encode(sha256(json_array(e.endpoint_key,e.member_path)),'hex'),1,16) AS version_key
FROM endpoint_bodies e JOIN ambiguous_endpoints a ON e.endpoint_key=a.endpoint_key AND e.member_path IS NOT DISTINCT FROM a.member_path
