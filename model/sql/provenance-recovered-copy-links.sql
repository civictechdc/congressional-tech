-- DM 7.5 recovered_copy (owner, 2026-11-02): a recovered copy (display kind recovered_document or
-- full_recording_recovered) whose body is byte-identical, sha and size, to a real body makes its
-- original link's own source file (DM 7.4) another address of the document holding that body
-- (grouping_steps: recovered_copy_members). One row per (link source file, body); other recovery
-- kinds keep their own documents.
-- ct-u9y4: a link accepted with several recovered copies moves only through the copy its own row
-- would show, the first in the recovery order (DM 7.5), or through another of its copies whose text
-- fingerprint equals that copy's. A lower-ranked copy with other text says nothing about the link:
-- 18 dead links sat in unrelated documents because a same-name file from another hearing was
-- fetched live ("Bowman Testimony.pdf", cae8e4ea34ec603a). One pass: the copies are ranked in a
-- window, and each relation is read once outside the two candidate lookups.
WITH copies AS (
 SELECT f.source_id,r.original_url,r.body_sha,r.bytes,p.fingerprint,
  first_value(r.body_sha) OVER (PARTITION BY f.source_id ORDER BY cast(r.imported_at AS TIMESTAMP WITH TIME ZONE) DESC NULLS LAST,
   r.body_sha,r.receipt_key,r.receipt_line,r.capture_index) AS shown_body,
  first_value(p.fingerprint) OVER (PARTITION BY f.source_id ORDER BY cast(r.imported_at AS TIMESTAMP WITH TIME ZONE) DESC NULLS LAST,
   r.body_sha,r.receipt_key,r.receipt_line,r.capture_index) AS shown_fingerprint
 FROM model_recovery_rows r
 JOIN effective_filenames n ON n.input_id='recovery:'||r.id
 JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
 -- Only the recovered copies' own fingerprints are read (candidate semi-join; the small set builds).
 LEFT JOIN (SELECT p.body_sha,max(p.fingerprint) AS fingerprint
  FROM (SELECT DISTINCT body_sha FROM model_recovery_rows WHERE kind IN ('recovered_document','full_recording_recovered')) c
  JOIN body_fingerprints p ON p.body_sha=c.body_sha GROUP BY p.body_sha) p ON p.body_sha=r.body_sha
 WHERE r.kind IN ('recovered_document','full_recording_recovered')
)
SELECT DISTINCT c.source_id,c.original_url,c.body_sha
FROM copies c JOIN body_evidence b ON b.body_sha=c.body_sha AND b.original_size=c.bytes
WHERE (c.body_sha=c.shown_body OR c.fingerprint=c.shown_fingerprint)
 AND EXISTS (SELECT 1 FROM source_files s WHERE s.body_sha=c.body_sha AND s.is_real_file)
