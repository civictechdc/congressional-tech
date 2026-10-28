SELECT component,array_agg(DISTINCT 'bodies/sha256/'||substr(body_sha,1,2)||'/'||body_sha||'.gz'
 ORDER BY 'bodies/sha256/'||substr(body_sha,1,2)||'/'||body_sha||'.gz') AS logical_keys,
 array_agg(DISTINCT body_sha ORDER BY body_sha) AS link_bodies
FROM document_members WHERE is_real_file GROUP BY component
