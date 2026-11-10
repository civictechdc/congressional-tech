-- DM 7.5 title rule: a document whose saved file has no reading title takes the reading title of
-- its first other-format file, in saved-file order. With none, it takes the listing-link text of
-- another copy of its saved bytes, in saved-file order: the name can come from an official copy that
-- no page lists, and the committee's link text still titles the document (ct-h8dr). The document row
-- reads the saved file's own reading title and link text first (document-normalized.sql).
WITH ranked AS (
 SELECT r.component,CASE WHEN r.body_sha=s.body_sha THEN a.listing_title ELSE a.reading_title END AS title,
  row_number() OVER(PARTITION BY r.component ORDER BY r.body_sha=s.body_sha,r.saved_rank) AS preference
 FROM saved_files s JOIN saved_files r ON r.component=s.component AND r.saved_rank>1
  AND (r.body_sha=s.body_sha OR r.format<>s.format)
 JOIN source_annotations a ON a.source_id=r.source_id
 WHERE s.saved_rank=1 AND CASE WHEN r.body_sha=s.body_sha THEN a.listing_title ELSE a.reading_title END IS NOT NULL
)
SELECT component,title FROM ranked WHERE preference=1
