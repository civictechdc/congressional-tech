-- Selected html_metadata readings of saved html document bodies only: the candidate set is
-- built from documents first and joined inside the readings scan (AGENTS.md), never grouped after.
WITH candidate_metadata_shas AS (
 SELECT DISTINCT arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha
 FROM base_normalized WHERE format='html' AND body_hex IS NOT NULL
)
SELECT r.body_sha,encode(r.body_sha,'hex') AS body_hex,r.parser_version,r.status,r.error_type,r.title,r.base_href,r.text_bytes,r.text_head,r.fields
FROM selected_readings r JOIN candidate_metadata_shas c ON r.body_sha=c.body_sha
WHERE r.parser='html_metadata'
