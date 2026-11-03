-- Every completed requested-name reading, not only the canonical alternate used for display fills.
-- A final-URL source can have several requested URLs; each disagreement needs its own triage row.
WITH requested AS (
 SELECT DISTINCT source_id,requested_filename,requested_url FROM capture_sources WHERE requested_filename IS NOT NULL
)
SELECT q.source_id,q.requested_filename,q.requested_url,
 f.filename_date,f.congress,
 -- Iceberg carries element field ids (document_kind is 19); the aggregated choices relation
 -- does not. Normalize the three public list fields so both sides concatenate as one type.
 arrow_cast(f.document_kind,'List(Utf8)') AS document_kind,
 arrow_cast(f.document_family,'List(Utf8)') AS document_family,
 arrow_cast(f.committee_code,'List(Utf8)') AS committee_code,
 row_number() OVER(PARTITION BY q.source_id ORDER BY q.requested_url,q.requested_filename) AS preference
FROM requested q JOIN filename_readings f ON f.filename=q.requested_filename AND f.source_url=q.requested_url
WHERE f.catalog_version={{CATALOG_VERSION}} AND f.status='completed'
