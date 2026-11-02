-- A ZIP is how files were captured. Once good contents are captured they are the documents;
-- a ZIP with none stays a document, counted as a recorded disposition.
WITH member_lines AS (
 SELECT DISTINCT receipt_key,receipt_line FROM capture_evidence WHERE member_path IS NOT NULL
)
SELECT DISTINCT z.sha256 FROM member_lines m JOIN good_archive_containers z
 ON z.receipt_key=m.receipt_key AND z.receipt_line=m.receipt_line
