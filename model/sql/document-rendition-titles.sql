-- DM 7.5 title rule: a document whose saved file has no reading title takes the
-- reading title of its first other-format file, in saved-file order.
WITH ranked AS (
 SELECT r.component,a.reading_title AS title,
  row_number() OVER(PARTITION BY r.component ORDER BY r.saved_rank) AS preference
 FROM saved_files s JOIN saved_files r ON r.component=s.component AND r.saved_rank>1 AND r.format<>s.format
 JOIN source_annotations a ON a.source_id=r.source_id
 WHERE s.saved_rank=1 AND a.reading_title IS NOT NULL
)
SELECT component,title FROM ranked WHERE preference=1
