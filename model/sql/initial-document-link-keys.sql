SELECT DISTINCT l.component,substr(f.body_sha,1,16) AS link_key FROM source_files f
JOIN source_labels l USING(source_id) WHERE f.is_real_file
UNION
SELECT DISTINCT component,substr(encode(sha256('url:'||original_url),'hex'),1,16) AS link_key FROM recovery_attachments
