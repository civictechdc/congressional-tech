-- A document's filename date and Congress come from every copy of its saved bytes, not only the saved
-- one: a name that follows a published convention (HHRG, HMKP, BILLS, CHRG ...; the reading's valid)
-- outranks a plain committee-site name, then the earliest value (identical bytes posted for several
-- meetings date from the first), so neither a newer copy nor crawl order re-dates the document.
-- One window pass picks both fields (one scan of the copies).
WITH copies AS (
 SELECT s.component,s.source_id,s.source_url,s.filename,s.first_fetched
 FROM saved_files s JOIN saved_files k ON k.component=s.component AND k.saved_rank=1 AND k.body_sha=s.body_sha
), named AS (
 SELECT c.*,
  CASE WHEN f.filename_date_status='completed' THEN f.filename_date END AS filename_date,coalesce(f.filename_date_valid,false) AS date_valid,
  CASE WHEN f.congress_status='completed' THEN f.congress END AS congress,coalesce(f.congress_valid,false) AS congress_valid
 FROM copies c JOIN source_filename_readings f ON f.source_id=c.source_id
)
SELECT component,
 max(filename_date) FILTER (WHERE date_choice=1) AS filename_date,
 max(congress) FILTER (WHERE congress_choice=1) AS congress
FROM (
 SELECT component,filename_date,congress,
  CASE WHEN filename_date IS NOT NULL THEN row_number() OVER(PARTITION BY component
   ORDER BY filename_date IS NULL,date_valid DESC,filename_date,first_fetched NULLS LAST,source_url,filename,source_id) END AS date_choice,
  CASE WHEN congress IS NOT NULL THEN row_number() OVER(PARTITION BY component
   ORDER BY congress IS NULL,congress_valid DESC,congress,first_fetched NULLS LAST,source_url,filename,source_id) END AS congress_choice
 FROM named
) GROUP BY component
