-- DM 7.8, ct-u9y4 (owner, 2026-11-11). Each recovery keeps its reviewed role (recovered-file-roles.json, keyed
-- by dead link and recovered body like a provenance decision): source_page, a capture of the dead page itself
-- beside the file it carried, stays on the link's document but is no recovered file of it (saved-recoveries.sql)
-- and its address is a source (document-addresses.sql); edition, another edition of the file the link shows,
-- moves to its own document: the one holding that body as a real file, else one of its own ('c:e:' and the
-- body), found by its body key (document-link-keys.sql); same_document and undecided stay, reviewed.
-- The registry and the real holders of edition bodies are the small sides, so they build.
WITH placed AS (
 SELECT r.* EXCLUDE(component),c.component,v.role
 FROM recovered_file_roles v RIGHT JOIN (recovery_attachments r JOIN review_components c ON c.node='c:'||r.component)
  ON v.original_url=r.original_url AND v.body_sha=r.body_sha
), held AS (
 SELECT f.body_sha,min(l.component) AS component
 FROM (SELECT DISTINCT body_sha FROM recovered_file_roles WHERE role='edition') e
 JOIN source_files f ON f.body_sha=e.body_sha AND f.is_real_file JOIN final_source_labels l ON l.source_id=f.source_id
 GROUP BY f.body_sha
)
SELECT p.* EXCLUDE(component),CASE WHEN p.role='edition' THEN coalesce(h.component,'c:e:'||p.body_sha) ELSE p.component END AS component
FROM held h RIGHT JOIN placed p ON p.role='edition' AND h.body_sha=p.body_sha
