SELECT substr(body_sha,1,16) AS link_key FROM source_files WHERE is_real_file
GROUP BY substr(body_sha,1,16) HAVING min(body_sha)<>max(body_sha)
