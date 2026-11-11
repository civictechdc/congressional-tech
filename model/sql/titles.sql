-- The one place a document's title is chosen (title design stage 1). Candidates in rank order: 0 a hand
-- correction (title-overrides.json, by link key); 1 the document's own page title, else its heading; 2 the
-- committee's link text for its saved file (for a recovery, its original address); 3 the page title of its
-- first other-format file, else the link text of another copy of its saved bytes, in saved-file order
-- (ct-h8dr: the name can come from an official copy no page lists); 4 a merged recovered copy's own title.
-- Text arrives free of link words (source-annotations-pages/-publisher read title-rules.json). A label alone
-- ("Testimony", "Biography"; title-rules.json kind 'label') names no document (ct-ccsi): the first candidate
-- that is not one wins; when every candidate is a label, the first takes the witness's name, else it stays only
-- when there is no filename to show. title_source names the winner; label_witness marks an assembled title.
-- Each candidate is judged once; every input is read once.
WITH rendition AS (
 SELECT r.component,CASE WHEN r.body_sha=s.body_sha THEN a.listing_title ELSE a.reading_title END AS text,
  CASE WHEN r.body_sha=s.body_sha THEN 'copy_link_text' ELSE 'other_format_'||a.reading_source END AS source,
  row_number() OVER(PARTITION BY r.component ORDER BY r.body_sha=s.body_sha,r.saved_rank) AS preference
 FROM saved_files s JOIN saved_files r ON r.component=s.component AND r.saved_rank>1
  AND (r.body_sha=s.body_sha OR r.format<>s.format)
 JOIN source_annotations a ON a.source_id=r.source_id
 WHERE s.saved_rank=1 AND CASE WHEN r.body_sha=s.body_sha THEN a.listing_title ELSE a.reading_title END IS NOT NULL
), candidates AS (
 SELECT k.component,0 AS rank,o.title AS text,'correction' AS source FROM title_overrides o JOIN document_link_keys k ON k.link_key=o.link_key
 UNION ALL SELECT component,1,own_title,own_title_source FROM base_normalized WHERE own_title IS NOT NULL
 UNION ALL SELECT component,2,link_title,'link_text' FROM base_normalized WHERE link_title IS NOT NULL
 UNION ALL SELECT component,3,text,source FROM rendition WHERE preference=1
 UNION ALL SELECT component,4,title,'recovered_copy' FROM recovered_copy_fills WHERE title IS NOT NULL
), ranked AS (
 SELECT c.*,g.pattern IS NOT NULL AS is_label,row_number() OVER(PARTITION BY c.component
  ORDER BY g.pattern IS NOT NULL,c.rank,c.text) AS pick
 FROM (SELECT pattern FROM title_rules WHERE kind='label') g
 RIGHT JOIN candidates c ON c.rank>0 AND regexp_like(trim(c.text),g.pattern)
), chosen AS (
 SELECT n.doc_key,
  CASE WHEN NOT f.is_label THEN f.text WHEN w.witness_name IS NOT NULL THEN f.text||' - '||w.witness_name
   WHEN coalesce(n.filename,'')='' THEN f.text END AS title,
  CASE WHEN NOT f.is_label THEN f.source WHEN w.witness_name IS NOT NULL THEN 'label_witness'
   WHEN coalesce(n.filename,'')='' THEN f.source END AS title_source
 FROM document_witness_keys w RIGHT JOIN (
  (SELECT * FROM ranked WHERE pick=1) f JOIN base_normalized n ON n.component=f.component
 ) ON w.component=f.component
)
SELECT doc_key,title,title_source FROM chosen WHERE title IS NOT NULL
