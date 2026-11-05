-- A document's filename date and Congress come from every copy of its saved bytes, not only the saved
-- one: a name that follows a published convention (HHRG, HMKP, BILLS, CHRG ...; the reading's valid)
-- outranks a committee site's '<sha256>.hhrg-...' copy of one (often dated the day it was posted, a
-- day before the hearing), which outranks a plain committee-site name; then the earliest value
-- (identical bytes posted for several meetings date from the first), so neither a newer copy nor
-- crawl order re-dates the document. A date after its copy was captured or outside its Congress (a
-- truncated '-2070906') is misread and ranks below every plausible one.
-- One window pass picks both fields (one scan of the copies).
WITH copies AS (
 SELECT s.component,s.source_id,s.source_url,s.filename,s.first_fetched
 FROM saved_files s JOIN saved_files k ON k.component=s.component AND k.saved_rank=1 AND k.body_sha=s.body_sha
), named AS (
 SELECT c.*,
  CASE WHEN f.filename_date_status='completed' THEN f.filename_date END AS filename_date,
  CASE WHEN f.filename_date_valid THEN 2
   WHEN regexp_like(coalesce(f.filename_date_name,''),'(?i)^[0-9a-f]{64}[.](hhrg|hmkp|hmtg)-') THEN 1 ELSE 0 END AS date_convention,
  CASE WHEN f.congress_status='completed' THEN f.congress END AS congress,
  CASE WHEN f.congress_valid THEN 2
   WHEN regexp_like(coalesce(f.congress_name,''),'(?i)^[0-9a-f]{64}[.](hhrg|hmkp|hmtg)-') THEN 1 ELSE 0 END AS congress_convention
 FROM copies c JOIN source_filename_readings f ON f.source_id=c.source_id
), judged AS (
 SELECT *,
  (first_fetched IS NULL OR filename_date<=cast(first_fetched AS DATE))
  AND (congress IS NULL OR date_part('year',filename_date) BETWEEN 2*congress+1787 AND 2*congress+1789) AS date_plausible
 FROM named
)
SELECT component,
 max(filename_date) FILTER (WHERE date_choice=1) AS filename_date,
 max(congress) FILTER (WHERE congress_choice=1) AS congress
FROM (
 SELECT component,filename_date,congress,
  CASE WHEN filename_date IS NOT NULL THEN row_number() OVER(PARTITION BY component
   ORDER BY filename_date IS NULL,date_plausible DESC,date_convention DESC,filename_date,first_fetched NULLS LAST,source_url,filename,source_id) END AS date_choice,
  CASE WHEN congress IS NOT NULL THEN row_number() OVER(PARTITION BY component
   ORDER BY congress IS NULL,congress_convention DESC,congress,first_fetched NULLS LAST,source_url,filename,source_id) END AS congress_choice
 FROM judged
) GROUP BY component
