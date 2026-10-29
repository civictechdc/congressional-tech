-- One membership edge per source, never a pairwise rendition clique.
SELECT 's:'||source_id AS left_node,'s:'||source_id AS right_node FROM source_files
UNION SELECT 's:'||source_id,'b:'||body_sha FROM source_files WHERE is_real_file
UNION SELECT 's:'||e.source_id,'f:'||encode(sha256(json_array(e.endpoint_key,e.member_path,f.fingerprint)),'hex')
 FROM fingerprints f JOIN endpoint_bodies e USING(body_sha) WHERE f.fingerprint IS NOT NULL
UNION SELECT 's:'||source_id,'r:'||group_kind||':'||group_id FROM valid_rendition_members
