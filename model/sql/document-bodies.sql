SELECT component,array_agg(DISTINCT 'bodies/sha256/'||substr(body_sha,1,2)||'/'||body_sha||'.gz'
 ORDER BY 'bodies/sha256/'||substr(body_sha,1,2)||'/'||body_sha||'.gz') AS logical_keys,
 array_agg(DISTINCT link_body ORDER BY link_body) AS link_bodies
FROM (
 SELECT component,body_sha,body_sha AS link_body FROM document_members WHERE is_real_file
 UNION ALL
 SELECT m.component,m.body_sha,z.body_sha FROM document_members m JOIN archive_container_links z ON m.source_id=z.source_id WHERE m.is_real_file
) GROUP BY component
