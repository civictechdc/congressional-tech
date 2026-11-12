-- DM 7.5 recovery order. A dead page's capture of itself is its file's source, not a recovered file (ct-u9y4,
-- final-recovery-attachments.sql): it is ranked with the files only to know whether the page is what the document
-- showed (page_shown: its body), whose title the document keeps on the file (owner, 2026-11-11), then left out.
-- Running windows only; a few thousand rows.
WITH ranked AS (
 SELECT r.*,row_number() OVER w AS link_rank,
  CASE WHEN first_value(r.role) OVER w='source_page' THEN first_value(r.body_sha) OVER w END AS page_shown
 FROM final_recovery_attachments r
 -- A ZIP with good contents is a source record, whichever way it entered, and its members are documents rather than recoveries.
 -- Shared with provenance-recovered-copy-links.sql via archive_provenance (ct-jcnd).
 WHERE {{NON_ARCHIVE_RECOVERY_FILTER}}
 WINDOW w AS (PARTITION BY component ORDER BY {{RECOVERY_ORDER}})
)
SELECT * EXCLUDE(link_rank),row_number() OVER(PARTITION BY component ORDER BY link_rank) AS saved_rank
FROM ranked WHERE role IS DISTINCT FROM 'source_page'
