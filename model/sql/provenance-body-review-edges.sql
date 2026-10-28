-- Body nodes already connect every real source of a body; never pair their names.
WITH bodies AS (SELECT DISTINCT body_sha,substr(body_sha,1,16) AS link_key FROM source_files WHERE is_real_file)
SELECT DISTINCT 'b:'||a.body_sha AS left_node,'b:'||b.body_sha AS right_node
FROM current_reviews r JOIN bodies a ON r.target=a.link_key
JOIN bodies b ON r.value_text=b.link_key WHERE r.verdict='duplicate_of'
AND NOT EXISTS (SELECT 1 FROM body_review_key_conflicts x WHERE x.link_key IN (a.link_key,b.link_key))
