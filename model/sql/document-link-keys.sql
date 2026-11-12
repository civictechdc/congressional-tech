SELECT DISTINCT l.component,substr(f.body_sha,1,16) AS link_key FROM final_source_labels l
JOIN source_files f USING(source_id) WHERE f.is_real_file
UNION
SELECT DISTINCT component,substr(encode(sha256('url:'||original_url),'hex'),1,16) AS link_key FROM final_recovery_attachments
WHERE role IS DISTINCT FROM 'edition'
UNION
-- An edition moved off its link is found by its body key (ct-u9y4); its link's key stays with the link's file.
SELECT DISTINCT component,substr(body_sha,1,16) AS link_key FROM final_recovery_attachments WHERE role='edition'
