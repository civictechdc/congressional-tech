-- DM 7.5 recovered_copy (owner, 2026-11-02): a recovered copy (display kind recovered_document or
-- full_recording_recovered) whose body is byte-identical, sha and size, to a real body makes its
-- original link's own source file (DM 7.4) another address of the document holding that body
-- (grouping_steps: recovered_copy_members). One row per (link source file, body); other recovery
-- kinds keep their own documents.
-- ct-u9y4: a link accepted with several recovered copies moves only through the copy its own row
-- would show, the first in the recovery order (DM 7.5), or through another copy whose text fingerprint
-- equals that copy's or whose full SHA pair was verified equivalent at this original URL (ct-m3h3).
-- A lower-ranked copy with other text says nothing about the link:
-- 18 dead links sat in unrelated documents because a same-name file from another hearing was
-- fetched live ("Bowman Testimony.pdf", cae8e4ea34ec603a). One pass: the copies are ranked in a
-- window, and each relation is read once outside the two candidate lookups.
WITH copies AS (
 SELECT f.source_id,r.original_url,r.body_sha,r.bytes,p.fingerprint,
  first_value(r.body_sha) OVER w AS shown_body,
  first_value(p.fingerprint) OVER w AS shown_fingerprint
 FROM model_recovery_rows r
 JOIN effective_filenames n ON n.input_id='recovery:'||r.id
 JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
 -- Only the recovered copies' own fingerprints are read (candidate semi-join; the small set builds).
 LEFT JOIN (SELECT p.body_sha,max(p.fingerprint) AS fingerprint
  FROM (SELECT DISTINCT body_sha FROM model_recovery_rows WHERE kind IN ('recovered_document','full_recording_recovered')) c
  JOIN body_fingerprints p ON p.body_sha=c.body_sha GROUP BY p.body_sha) p ON p.body_sha=r.body_sha
 WHERE r.kind IN ('recovered_document','full_recording_recovered')
  AND {{NON_ARCHIVE_RECOVERY_FILTER}}
 WINDOW w AS (PARTITION BY f.source_id ORDER BY {{RECOVERY_ORDER}})
)
SELECT DISTINCT c.source_id,c.original_url,c.body_sha,
 CASE WHEN e.body_sha IS NOT NULL THEN c.shown_body END AS equivalent_shown_body_sha
FROM (SELECT original_url,body_sha,equivalent_body_sha FROM recovered_file_roles WHERE equivalent_body_sha IS NOT NULL) e
RIGHT JOIN (copies c JOIN body_evidence b ON b.body_sha=c.body_sha AND b.original_size=c.bytes)
 ON e.original_url=c.original_url
 AND ((e.body_sha=c.body_sha AND e.equivalent_body_sha=c.shown_body)
      OR (e.body_sha=c.shown_body AND e.equivalent_body_sha=c.body_sha))
WHERE (c.body_sha=c.shown_body OR c.fingerprint=c.shown_fingerprint OR e.body_sha IS NOT NULL)
 AND EXISTS (SELECT 1 FROM source_files s WHERE s.body_sha=c.body_sha AND s.is_real_file)
